import pytest

from parchi.ingestion.names import (
    UnsafeNameError,
    UnsupportedTypeError,
    clean_display_name,
    extension_of,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  inv_0421.pdf  ", "inv_0421.pdf"),
        ("bill (1).PDF", "bill (1).PDF"),
        ("Cafe\u0301.png", "Café.png"),  # NFC: e + combining accent becomes é
        ("चाय बिल.jpg", "चाय बिल.jpg"),
    ],
)
def test_clean_names_are_kept(raw: str, expected: str) -> None:
    assert clean_display_name(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "   ",
        "..",
        "../etc/passwd",
        "folder/bill.pdf",
        "C:\\Users\\bill.pdf",
        "bill\n.pdf",
        "bill\x00.pdf",
        "bill\u202e.pdf",  # right-to-left override, used to disguise extensions
    ],
)
def test_unsafe_names_are_rejected(raw: str | None) -> None:
    with pytest.raises(UnsafeNameError):
        clean_display_name(raw)


def test_long_names_are_cut_keeping_the_extension() -> None:
    name = clean_display_name("a" * 300 + ".pdf")
    assert len(name) == 255
    assert name.endswith(".pdf")


@pytest.mark.parametrize(
    ("name", "ext"),
    [("bill.pdf", "pdf"), ("PHOTO.JPG", "jpg"), ("sheet.v2.xlsx", "xlsx"), ("a.heic", "heic")],
)
def test_accepted_extensions(name: str, ext: str) -> None:
    assert extension_of(name) == ext


@pytest.mark.parametrize("name", ["setup.exe", "notes.txt", "noextension", "archive.zip", "pdf"])
def test_other_extensions_are_refused(name: str) -> None:
    with pytest.raises(UnsupportedTypeError):
        extension_of(name)
