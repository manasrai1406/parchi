from parchi.extraction.ocr import Word
from parchi.extraction.ocr_layout import mean_score, words_to_lines


def word(text: str, left: float, top: float, height: float = 20, score: float = 0.9) -> Word:
    return Word(text, score, left, top, left + 10 * len(text), top + height)


def test_pieces_on_one_line_are_joined_left_to_right() -> None:
    words = [
        word("1180.00", 400, 102),
        word("Grand", 50, 100),
        word("Total", 120, 98),  # slightly higher: same printed line
        word("Blue Tokai", 50, 20),
    ]
    assert words_to_lines(words) == ["Blue Tokai", "Grand Total 1180.00"]


def test_lines_close_together_stay_separate() -> None:
    words = [word("Sub Total 1000.00", 50, 100), word("CGST 90.00", 50, 124)]
    assert words_to_lines(words) == ["Sub Total 1000.00", "CGST 90.00"]


def test_no_words_no_lines() -> None:
    assert words_to_lines([]) == []
    assert mean_score([]) == 0.0


def test_confidence_is_weighted_by_text_length() -> None:
    words = [word("Grand Total 1180.00", 0, 0, score=1.0), word("x", 0, 50, score=0.0)]
    assert round(mean_score(words), 2) == 0.95


def test_spaces_ocr_dropped_are_put_back_where_rules_need_them() -> None:
    from parchi.extraction.ocr_layout import tidy

    assert tidy("14 Aug 202618:42") == "14 Aug 2026 18:42"
    assert tidy("Grand TotalINR 540.00") == "Grand Total INR 540.00"
    assert tidy("Total540.00") == "Total 540.00"
    assert tidy("CGST@9% 45.00") == "CGST@9% 45.00"  # not a digit or rupee after the label
    assert tidy("Invoice No INV0421") == "Invoice No INV0421"  # numbers stay intact
    assert tidy("Subtotal₹1,000.00") == "Subtotal ₹1,000.00"
