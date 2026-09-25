"""Untrusted file names (hard rule 10, D-013 item 8, D-016)."""

import unicodedata

MAX_NAME_LENGTH = 255

# Accepted at upload (D-016). Phase 3 checks the real bytes.
ALLOWED_EXTENSIONS = frozenset({"pdf", "jpg", "jpeg", "png", "webp", "heic", "xlsx", "xls", "csv"})


class UnsafeNameError(ValueError):
    """The name has a path separator or control character, or is empty."""


class UnsupportedTypeError(ValueError):
    """The extension is not one we accept."""


def _is_control(char: str) -> bool:
    return unicodedata.category(char) in {"Cc", "Cf", "Zl", "Zp"}


def clean_display_name(raw: str | None) -> str:
    """Trim, normalize and length-limit a name. Reject separators and control characters.

    Nothing is silently stripped: a name that needs more than trimming is refused.
    """
    name = unicodedata.normalize("NFC", raw or "").strip()
    if not name or name in {".", ".."}:
        raise UnsafeNameError("The file has no name.")
    if "/" in name or "\\" in name:
        raise UnsafeNameError("File names cannot contain / or \\.")
    if any(_is_control(char) for char in name):
        raise UnsafeNameError("File names cannot contain control characters.")
    if len(name) > MAX_NAME_LENGTH:
        stem, dot, ext = name.rpartition(".")
        if dot and 0 < len(ext) <= 10:
            name = stem[: MAX_NAME_LENGTH - len(ext) - 1] + "." + ext
        else:
            name = name[:MAX_NAME_LENGTH]
    return name


def extension_of(name: str) -> str:
    """The lowercase extension, if it is one we accept."""
    _, dot, ext = name.rpartition(".")
    ext = ext.lower()
    if not dot or ext not in ALLOWED_EXTENSIONS:
        accepted = ", ".join(sorted(ALLOWED_EXTENSIONS))
        raise UnsupportedTypeError(f"This file type is not accepted. Accepted: {accepted}.")
    return ext
