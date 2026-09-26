"""Gemini (Google) behind the AI interface (D-035, D-041)."""

import json

import httpx
from google import genai
from google.genai import errors, types

from parchi.ai.base import AiCallError, AiInput, AiOutput, Approval
from parchi.ai.prompt import INSTRUCTIONS, RECEIPTS_SCHEMA, SYSTEM_PROMPT
from parchi.db.enums import AiProvider

# Answers that stop for these reasons are not receipts: say why instead.
BLOCKED = {
    types.FinishReason.SAFETY,
    types.FinishReason.RECITATION,
    types.FinishReason.BLOCKLIST,
    types.FinishReason.PROHIBITED_CONTENT,
    types.FinishReason.SPII,
    types.FinishReason.IMAGE_SAFETY,
    types.FinishReason.IMAGE_PROHIBITED_CONTENT,
}


def _contents(item: AiInput) -> list[types.Part]:
    """The file first, then the instructions."""
    parts: list[types.Part] = []
    if item.image is not None:
        parts.append(types.Part.from_bytes(data=item.image, mime_type=item.image_type or ""))
    elif item.pdf is not None:
        parts.append(types.Part.from_bytes(data=item.pdf, mime_type="application/pdf"))
    else:
        parts.append(types.Part.from_text(text=f"File {item.filename}:\n\n{item.text}"))
    parts.append(types.Part.from_text(text=INSTRUCTIONS))
    return parts


def _error(exc: errors.APIError, model: str) -> AiCallError:
    """A message that is safe to show and log; it never contains receipt content."""
    code = exc.code
    if code in (401, 403) or "API_KEY" in str(exc.status or ""):
        return AiCallError("Google rejected the API key, or it may not use this model.")
    if code == 404:
        return AiCallError(f"Google does not know the model {model}.")
    if code == 429:
        return AiCallError("Gemini's rate limit or quota was reached. Try again later.")
    if code in (400, 413):
        return AiCallError("Gemini could not accept this file (too large or unsupported).")
    if code in (500, 503):
        return AiCallError("Gemini is busy right now (high demand). Try again in a few minutes.")
    if code in (408, 504):
        return AiCallError("Gemini did not answer in time.")
    return AiCallError(f"Gemini returned an error ({code}).")


class GeminiProvider:
    name = AiProvider.GEMINI

    def __init__(self, api_key: str, model: str, timeout: float) -> None:
        self.model = model
        self._client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                timeout=int(timeout * 1000),  # milliseconds
                retry_options=types.HttpRetryOptions(attempts=3),
            ),
        )

    async def extract(self, approval: Approval, item: AiInput) -> AiOutput:
        if approval.provider != self.name:
            raise AiCallError("This approval is for a different provider.")
        try:
            response = await self._client.aio.models.generate_content(
                model=approval.model,
                contents=_contents(item),
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    response_mime_type="application/json",
                    response_json_schema=RECEIPTS_SCHEMA,
                    # No tools are offered, so the SDK's function calling stays off.
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                ),
            )
        except errors.APIError as exc:
            raise _error(exc, approval.model) from exc
        except (httpx.TimeoutException, TimeoutError) as exc:
            raise AiCallError("Gemini did not answer in time.") from exc
        except (httpx.TransportError, OSError) as exc:
            raise AiCallError(
                "Gemini could not be reached. Check the internet connection."
            ) from exc

        feedback = response.prompt_feedback
        if feedback is not None and feedback.block_reason:
            raise AiCallError("Gemini declined to read this file.")
        candidate = response.candidates[0] if response.candidates else None
        if candidate is not None and candidate.finish_reason in BLOCKED:
            raise AiCallError("Gemini declined to read this file.")
        if candidate is not None and candidate.finish_reason == types.FinishReason.MAX_TOKENS:
            raise AiCallError("Gemini's answer was cut off (too many receipts in one file).")
        text = response.text
        if not text:
            raise AiCallError("Gemini returned no answer.")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise AiCallError("Gemini's answer was not valid JSON.") from exc
        usage = response.usage_metadata
        return AiOutput(
            data=data,
            input_tokens=usage.prompt_token_count if usage else None,
            output_tokens=usage.candidates_token_count if usage else None,
            request_id=response.response_id,
        )
