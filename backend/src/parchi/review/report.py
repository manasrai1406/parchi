"""The error report: a PDF per file, or one combined PDF (D-031).

Standard PDF fonts have no rupee symbol, so amounts print as "Rs.".
"""

import io
from datetime import datetime
from decimal import Decimal
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from parchi.schemas.api import FileDetail

STYLES = getSampleStyleSheet()
SMALL = ParagraphStyle("small", parent=STYLES["BodyText"], fontSize=8, leading=10)
MUTED = colors.HexColor("#5B6B64")
GRID = TableStyle(
    [
        ("FONT", (0, 0), (-1, -1), "Helvetica", 8),
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEF2F0")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#C9D4CF")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]
)


def _text(value: object) -> str:
    """Printable, XML-safe text; rupee symbols become Rs."""
    if value is None:
        return "-"
    if isinstance(value, Decimal):
        return f"Rs. {value:,.2f}"
    if isinstance(value, datetime):
        return f"{value:%d %b %Y %H:%M} UTC"
    return escape(str(value).replace("₹", "Rs. "))


def _p(value: object, style: ParagraphStyle = SMALL) -> Paragraph:
    return Paragraph(_text(value), style)


def _table(rows: list[list[object]], widths: list[float]) -> Table:
    table = Table([[_p(cell) for cell in row] for row in rows], colWidths=widths, repeatRows=1)
    table.setStyle(GRID)
    return table


def _file_story(file: FileDetail) -> list:
    story: list = [
        Paragraph(f"Error report: {_text(file.ref_no)}", STYLES["Title"]),
        _table(
            [
                ["File", "Status", "Type", "Uploaded", "Copy of"],
                [
                    file.original_name,
                    file.status.value,
                    file.kind.value if file.kind else None,
                    file.uploaded_at,
                    file.duplicate_of.ref_no if file.duplicate_of else None,
                ],
            ],
            [60 * mm, 25 * mm, 22 * mm, 35 * mm, 32 * mm],
        ),
    ]
    if file.error:
        story += [Spacer(0, 3 * mm), _p(f"Reason: {file.error}", STYLES["BodyText"])]

    story += [Spacer(0, 5 * mm), Paragraph("Problems", STYLES["Heading2"])]
    if file.flags:
        story.append(
            _table(
                [["Check", "Severity", "Detail", "Receipt", "State"]]
                + [
                    [
                        flag.type.value.replace("_", " "),
                        flag.severity.value,
                        flag.detail,
                        next((r.ref_no for r in file.receipts if r.id == flag.receipt_id), None),
                        f"resolved by {flag.resolved_by}" if flag.resolved else "open",
                    ]
                    for flag in file.flags
                ],
                [28 * mm, 16 * mm, 78 * mm, 30 * mm, 22 * mm],
            )
        )
    else:
        story.append(_p("No problems were recorded.", STYLES["BodyText"]))

    story += [Spacer(0, 5 * mm), Paragraph("Extraction runs", STYLES["Heading2"])]
    if not file.runs:
        story.append(_p("The file has not been read yet.", STYLES["BodyText"]))
    for run in file.runs:
        state = "accepted" if run.accepted else "not accepted"
        who = f", approved by {run.ai_approved_by}" if run.ai_approved_by else ""
        story.append(
            _p(
                f"Run {run.id}: {run.parser.value}, {state}"
                f"{', confidence ' + format(run.confidence, '.0%') if run.confidence else ''}"
                f"{who}. {('Error: ' + run.error) if run.error else ''}",
                STYLES["BodyText"],
            )
        )
        if run.result:
            story.append(
                _table(
                    [["Vendor", "Number", "Date", "Subtotal", "Tax", "Total", "Items"]]
                    + [
                        [
                            r.vendor,
                            r.receipt_number,
                            r.receipt_date,
                            r.subtotal,
                            r.tax,
                            r.total,
                            len(r.line_items),
                        ]
                        for r in run.result
                    ],
                    [45 * mm, 28 * mm, 20 * mm, 22 * mm, 20 * mm, 22 * mm, 13 * mm],
                )
            )
        story.append(Spacer(0, 3 * mm))

    story += [
        Spacer(0, 4 * mm),
        Paragraph(
            f"To find this file in the logs, search for {_text(file.ref_no)}"
            + (f" or run_id {file.runs[0].id}" if file.runs else "")
            + ".",
            ParagraphStyle("foot", parent=SMALL, textColor=MUTED),
        ),
    ]
    return story


def build_report(files: list[FileDetail]) -> bytes:
    """One PDF; each file starts on a new page."""
    out = io.BytesIO()
    document = SimpleDocTemplate(
        out,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        title="Parchi error report",
    )
    story: list = []
    for index, file in enumerate(files):
        if index:
            story.append(PageBreak())
        story += _file_story(file)
    if not story:
        story = [Paragraph("No files need attention.", STYLES["BodyText"])]
    document.build(story)
    return out.getvalue()
