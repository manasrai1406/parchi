"""Claude (Anthropic) behind the AI interface (D-035)."""

import base64
import json
from typing import Any

import anthropic

from parchi.ai.base import AiCallError, AiInput, AiOutput, Approval
from parchi.ai.prompt import INSTRUCTIONS, RECEIPTS_SCHEMA, SYSTEM_PROMPT
from parchi.db.enums import AiProvider

MAX_TOKENS = 16000


def _content(item: AiInput) -> list[dict[str, Any]]:
    """The file first, then the instructions."""
    blocks: list[dict[str, Any]] = []
    if item.image is not None:
        blocks.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": item.image_type,
                    "data": base64.standard_b64encode(item.image).decode("ascii"),
                },
            }
        )
    elif item.pdf is not None:
        blocks.append(
            {
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": base64.standard_b64encode(item.pdf).decode("ascii"),
                },
            }
        )
    else:
        blocks.append({"type": "text", "text": f"File {item.filename}:\n\n{item.text}"})
    blocks.append({"type": "text", "text": INSTRUCTIONS})
    return blocks


class ClaudeProvider:
    name = AiProvider.ANTHROPIC

    def __init__(self, api_key: str, model: str, timeout: float) -> None:
        self.model = model
        self._client = anthropic.AsyncAnthropic(api_key=api_key, timeout=timeout, max_retries=2)

    async def extract(self, approval: Approval, item: AiInput) -> AiOutput:
        if approval.provider != self.name:
            raise AiCallError("This approval is for a different provider.")
        try:
            response = await self._client.messages.create(
                model=approval.model,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": _content(item)}],
                output_config={
                    "effort": "medium",
                    "format": {"type": "json_schema", "schema": RECEIPTS_SCHEMA},
                },
            )
        except anthropic.AuthenticationError as exc:
            raise AiCallError("Anthropic rejected the API key. Check ANTHROPIC_API_KEY.") from exc
        except anthropic.PermissionDeniedError as exc:
            raise AiCallError("The Anthropic API key may not use this model.") from exc
        except anthropic.NotFoundError as exc:
            raise AiCallError(f"Anthropic does not know the model {approval.model}.") from exc
        except anthropic.RateLimitError as exc:
            raise AiCallError("Anthropic's rate limit was reached. Try again later.") from exc
        except anthropic.BadRequestError as exc:
            raise AiCallError(
                "Anthropic could not accept this file (too large or unsupported)."
            ) from exc
        except anthropic.APITimeoutError as exc:
            raise AiCallError("Anthropic did not answer in time.") from exc
        except anthropic.APIConnectionError as exc:
            raise AiCallError(
                "Anthropic could not be reached. Check the internet connection."
            ) from exc
        except anthropic.APIStatusError as exc:
            raise AiCallError(f"Anthropic returned an error ({exc.status_code}).") from exc

        if response.stop_reason == "refusal":
            raise AiCallError("Claude declined to read this file.")
        if response.stop_reason == "max_tokens":
            raise AiCallError("Claude's answer was cut off (too many receipts in one file).")
        text = next((block.text for block in response.content if block.type == "text"), None)
        if text is None:
            raise AiCallError("Claude returned no answer.")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise AiCallError("Claude's answer was not valid JSON.") from exc
        return AiOutput(
            data=data,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            request_id=response._request_id,
        )
