"""Enumerations stored in the database.

Each is a varchar column with a named CHECK constraint (D-012). Adding a value means
adding it here and writing a migration that replaces the CHECK constraint.
"""

from enum import StrEnum


class FileStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    PARSED = "parsed"
    NEEDS_REVIEW = "needs_review"
    AI_PROCESSING = "ai_processing"
    FLAGGED = "flagged"
    RESOLVED = "resolved"
    REJECTED = "rejected"
    FAILED = "failed"


class FileKind(StrEnum):
    EXCEL = "excel"
    CSV = "csv"
    PDF_TEXT = "pdf_text"
    PDF_SCAN = "pdf_scan"
    IMAGE = "image"


class RunParser(StrEnum):
    EXCEL = "excel"
    CSV = "csv"
    PDF_TEXT = "pdf_text"
    PDF_SCAN = "pdf_scan"
    IMAGE = "image"
    AI = "ai"
    MANUAL = "manual"


LIBRARY_PARSERS: tuple[RunParser, ...] = (
    RunParser.EXCEL,
    RunParser.CSV,
    RunParser.PDF_TEXT,
    RunParser.PDF_SCAN,
    RunParser.IMAGE,
)


class AiProvider(StrEnum):
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    GEMINI = "gemini"


class FlagType(StrEnum):
    UNREADABLE = "unreadable"
    VALIDATION_FAILED = "validation_failed"
    PARSER_CONFLICT = "parser_conflict"
    DUPLICATE_RECEIPT = "duplicate_receipt"
    ARITHMETIC_MISMATCH = "arithmetic_mismatch"


class FlagSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


# The categories every installation starts with (D-009). They live in the categories
# table, where people can add their own (D-026); built-in ones cannot be removed.
BUILTIN_CATEGORIES: tuple[str, ...] = (
    "Fuel",
    "Travel",
    "Food",
    "Office",
    "Utilities",
    "Maintenance",
    "Services",
    "Other",
)
