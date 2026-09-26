"""The AI adapters, prompt and approval object, without any network (D-035, D-036)."""

import asyncio
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from parchi.ai.base import AiCallError, AiInput, Approval, ApprovalMissingError
from parchi.ai.claude import ClaudeProvider
from parchi.ai.openai_provider import OpenAiProvider
from parchi.ai.prompt import RECEIPTS_SCHEMA, to_receipts
from parchi.db.enums import AiProvider, RunParser

ANSWER = {
    "receipts": [
        {
            "vendor": "  Sharma Traders ",
            "receipt_number": "ST/2026/0421",
            "receipt_date": "2026-08-14",
            "subtotal": "1,600.00",
            "tax": "288",
            "total": "1888.00",
            "line_items": [
                {"description": "A4 paper", "quantity": "4", "unit_price": "250", "amount": "1000"},
                {"description": "", "quantity": None, "unit_price": None, "amount": "5"},
                {"description": "Stapler", "quantity": None, "unit_price": None, "amount": None},
            ],
        }
    ]
}
NOW = datetime(2026, 9, 26, tzinfo=UTC)


def approval(provider: AiProvider, model: str = "test-model") -> Approval:
    return Approval(1, provider, model, "local user", NOW)


def run_row(**fields: Any) -> SimpleNamespace:
    base = {
        "id": 7,
        "parser": RunParser.AI,
        "provider": AiProvider.ANTHROPIC,
        "model": "claude-sonnet-5",
        "ai_approved_by": "local user",
        "ai_approved_at": NOW,
    }
    return SimpleNamespace(**(base | fields))


# --- approval ---------------------------------------------------------------------------


def test_an_approval_can_only_come_from_an_approved_ai_run() -> None:
    assert Approval.from_run(run_row()).approved_by == "local user"


@pytest.mark.parametrize(
    "change",
    [
        {"parser": RunParser.PDF_TEXT},
        {"ai_approved_by": None},
        {"ai_approved_at": None},
        {"provider": None},
        {"model": None},
    ],
)
def test_without_a_recorded_approval_there_is_no_approval(change: dict[str, Any]) -> None:
    with pytest.raises(ApprovalMissingError):
        Approval.from_run(run_row(**change))


# --- prompt and schema ------------------------------------------------------------------


def test_the_schema_is_strict_everywhere() -> None:
    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node["additionalProperties"] is False
                assert set(node["required"]) == set(node["properties"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(RECEIPTS_SCHEMA)


def test_answers_are_normalized_like_library_results() -> None:
    (receipt,) = to_receipts(ANSWER, source="AI (Claude)")
    assert receipt.vendor == "Sharma Traders"
    assert receipt.receipt_date == date(2026, 8, 14)
    assert (receipt.subtotal, receipt.tax, receipt.total) == (
        Decimal("1600.00"),
        Decimal("288.00"),
        Decimal("1888.00"),
    )
    # Items without a description or an amount are dropped, not guessed.
    assert [i.description for i in receipt.line_items] == ["A4 paper"]
    assert receipt.confidence == 0.9


# --- Claude adapter (mocked client: nothing is sent) --------------------------------------


class FakeMessages:
    def __init__(self, response: Any) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self.response


def claude_response(text: str, stop_reason: str = "end_turn") -> SimpleNamespace:
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=2100, output_tokens=380),
        _request_id="req_1",
    )


def claude_with(response: Any) -> tuple[ClaudeProvider, FakeMessages]:
    provider = ClaudeProvider("sk-test", "claude-sonnet-5", 30)
    messages = FakeMessages(response)
    provider._client = SimpleNamespace(messages=messages)  # type: ignore[assignment]
    return provider, messages


def test_claude_gets_the_image_the_instructions_and_the_schema() -> None:
    provider, messages = claude_with(claude_response(json.dumps(ANSWER)))
    item = AiInput(filename="bill.jpg", image=b"\xff\xd8\xffjpeg", image_type="image/jpeg")

    output = asyncio.run(provider.extract(approval(AiProvider.ANTHROPIC, "claude-sonnet-5"), item))

    (call,) = messages.calls
    assert call["model"] == "claude-sonnet-5"
    blocks = call["messages"][0]["content"]
    assert blocks[0]["type"] == "image"
    assert blocks[0]["source"]["media_type"] == "image/jpeg"
    assert blocks[1]["type"] == "text"
    assert call["output_config"]["format"] == {"type": "json_schema", "schema": RECEIPTS_SCHEMA}
    assert (output.input_tokens, output.output_tokens, output.request_id) == (2100, 380, "req_1")
    assert output.data == ANSWER


def test_claude_gets_a_pdf_as_a_document() -> None:
    provider, messages = claude_with(claude_response(json.dumps(ANSWER)))
    asyncio.run(
        provider.extract(approval(AiProvider.ANTHROPIC), AiInput(filename="a.pdf", pdf=b"%PDF-1.4"))
    )
    block = messages.calls[0]["messages"][0]["content"][0]
    assert (block["type"], block["source"]["media_type"]) == ("document", "application/pdf")


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (claude_response("", stop_reason="refusal"), "declined"),
        (claude_response('{"receipts": [', stop_reason="max_tokens"), "cut off"),
        (claude_response("not json"), "not valid JSON"),
    ],
)
def test_claude_problems_become_readable_errors(response: Any, message: str) -> None:
    provider, _ = claude_with(response)
    with pytest.raises(AiCallError, match=message):
        asyncio.run(
            provider.extract(approval(AiProvider.ANTHROPIC), AiInput(filename="a", text="x"))
        )


def test_an_approval_for_another_provider_is_refused() -> None:
    provider, messages = claude_with(claude_response("{}"))
    with pytest.raises(AiCallError):
        asyncio.run(provider.extract(approval(AiProvider.OPENAI), AiInput(filename="a", text="x")))
    assert messages.calls == []


# --- OpenAI adapter (mocked client) -------------------------------------------------------


class FakeResponses:
    def __init__(self, response: Any) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self.response


def openai_response(text: str, refusal: bool = False) -> SimpleNamespace:
    part = (
        SimpleNamespace(type="refusal", refusal="no")
        if refusal
        else SimpleNamespace(type="output_text")
    )
    return SimpleNamespace(
        output=[SimpleNamespace(type="message", content=[part])],
        output_text=text,
        usage=SimpleNamespace(input_tokens=1500, output_tokens=300),
    )


def openai_with(response: Any) -> tuple[OpenAiProvider, FakeResponses]:
    provider = OpenAiProvider("sk-test", "gpt-6-sol", 30)
    responses = FakeResponses(response)
    provider._client = SimpleNamespace(responses=responses)  # type: ignore[assignment]
    return provider, responses


def test_openai_gets_the_pdf_and_a_strict_schema() -> None:
    provider, responses = openai_with(openai_response(json.dumps(ANSWER)))

    output = asyncio.run(
        provider.extract(
            approval(AiProvider.OPENAI, "gpt-6-sol"), AiInput(filename="a.pdf", pdf=b"%PDF")
        )
    )

    (call,) = responses.calls
    part = call["input"][1]["content"][0]
    assert part["type"] == "input_file"
    assert part["file_data"].startswith("data:application/pdf;base64,")
    assert call["text"]["format"]["strict"] is True
    assert call["text"]["format"]["schema"] == RECEIPTS_SCHEMA
    assert (output.input_tokens, output.output_tokens) == (1500, 300)


def test_openai_image_goes_as_a_data_url() -> None:
    provider, responses = openai_with(openai_response(json.dumps(ANSWER)))
    item = AiInput(filename="a.png", image=b"\x89PNG", image_type="image/png")
    asyncio.run(provider.extract(approval(AiProvider.OPENAI), item))
    part = responses.calls[0]["input"][1]["content"][0]
    assert part["type"] == "input_image"
    assert part["image_url"].startswith("data:image/png;base64,")


def test_openai_refusal_becomes_an_error() -> None:
    provider, _ = openai_with(openai_response("", refusal=True))
    with pytest.raises(AiCallError, match="declined"):
        asyncio.run(provider.extract(approval(AiProvider.OPENAI), AiInput(filename="a", text="x")))
