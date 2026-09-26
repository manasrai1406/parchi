"""OpenAI behind the AI interface (D-035), using the Responses API."""

import base64
import json
from typing import Any

import openai

from parchi.ai.base import AiCallError, AiInput, AiOutput, Approval
from parchi.ai.prompt import INSTRUCTIONS, RECEIPTS_SCHEMA, SYSTEM_PROMPT
from parchi.db.enums import AiProvider


def _content(item: AiInput) -> list[dict[str, Any]]:
    """The file first, then the instructions."""
    parts: list[dict[str, Any]] = []
    if item.image is not None:
        data = base64.b64encode(item.image).decode("ascii")
        parts.append({"type": "input_image", "image_url": f"data:{item.image_type};base64,{data}"})
    elif item.pdf is not None:
        data = base64.b64encode(item.pdf).decode("ascii")
        parts.append(
            {
                "type": "input_file",
                "filename": item.filename,
                "file_data": f"data:application/pdf;base64,{data}",
            }
        )
    else:
        parts.append({"type": "input_text", "text": f"File {item.filename}:\n\n{item.text}"})
    parts.append({"type": "input_text", "text": INSTRUCTIONS})
    return parts


class OpenAiProvider:
    name = AiProvider.OPENAI

    def __init__(self, api_key: str, model: str, timeout: float) -> None:
        self.model = model
        self._client = openai.AsyncOpenAI(api_key=api_key, timeout=timeout, max_retries=2)

    async def extract(self, approval: Approval, item: AiInput) -> AiOutput:
        if approval.provider != self.name:
            raise AiCallError("This approval is for a different provider.")
        try:
            response = await self._client.responses.create(
                model=approval.model,
                input=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": _content(item)},
                ],
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "receipts",
                        "schema": RECEIPTS_SCHEMA,
                        "strict": True,
                    }
                },
            )
        except openai.AuthenticationError as exc:
            raise AiCallError("OpenAI rejected the API key. Check OPENAI_API_KEY.") from exc
        except openai.PermissionDeniedError as exc:
            raise AiCallError("The OpenAI API key may not use this model.") from exc
        except openai.NotFoundError as exc:
            raise AiCallError(f"OpenAI does not know the model {approval.model}.") from exc
        except openai.RateLimitError as exc:
            raise AiCallError("OpenAI's rate limit or quota was reached. Try again later.") from exc
        except openai.BadRequestError as exc:
            raise AiCallError(
                "OpenAI could not accept this file (too large or unsupported)."
            ) from exc
        except openai.APITimeoutError as exc:
            raise AiCallError("OpenAI did not answer in time.") from exc
        except openai.APIConnectionError as exc:
            raise AiCallError(
                "OpenAI could not be reached. Check the internet connection."
            ) from exc
        except openai.APIStatusError as exc:
            raise AiCallError(f"OpenAI returned an error ({exc.status_code}).") from exc

        for output in response.output:
            if getattr(output, "type", None) != "message":
                continue
            for part in output.content:
                if getattr(part, "type", None) == "refusal":
                    raise AiCallError("OpenAI declined to read this file.")
        text = response.output_text
        if not text:
            raise AiCallError("OpenAI returned no answer.")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise AiCallError("OpenAI's answer was not valid JSON.") from exc
        usage = response.usage
        return AiOutput(
            data=data,
            input_tokens=usage.input_tokens if usage else None,
            output_tokens=usage.output_tokens if usage else None,
            request_id=getattr(response, "_request_id", None),
        )
