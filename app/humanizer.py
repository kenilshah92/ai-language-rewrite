from __future__ import annotations

import json
import hashlib
from pathlib import Path

from openai import OpenAI

from app.models import TextBlock
from app.document_rewriter import ContentBlock


class HumanizerError(RuntimeError):
    pass


class Humanizer:
    def __init__(self, prompt_path: Path, model: str, client: OpenAI | None = None):
        self.prompt_path = prompt_path
        self.model = model
        self.prompt_text = prompt_path.read_text(encoding="utf-8").strip()
        self.prompt_sha256 = hashlib.sha256(self.prompt_text.encode()).hexdigest()
        self.response_ids = []
        self.client = client or OpenAI(timeout=600.0, max_retries=1)

    def rewrite(self, blocks: list[TextBlock | ContentBlock], repairs: dict | None = None) -> dict[str, str]:
        if not blocks:
            return {}

        prompt = self.prompt_text
        items = [
            {
                "id": block.id,
                "text": block.text,
                "maximum_characters": block.character_budget,
                "context": getattr(block, "context", ""),
                "repair": (repairs or {}).get(block.id),
            }
            for block in blocks
        ]
        response = self.client.responses.create(
            model=self.model,
            instructions=(
                prompt
                + "\n\nReturn valid JSON only, with this shape: "
                + '{"rewrites":[{"id":"block id","text":"rewritten text"}]}. '
                + "Include every input id exactly once. Do not add commentary."
            ),
            input=json.dumps({"blocks": items}, ensure_ascii=False),
        )

        self.response_ids.append(getattr(response, "id", None))
        try:
            payload = _parse_json_object(response.output_text)
            rows = payload["rewrites"]
            if not isinstance(rows, list) or any(not isinstance(row, dict) or not isinstance(row.get("id"), str) or not isinstance(row.get("text"), str) for row in rows):
                raise ValueError("Invalid row types")
            if len({row["id"] for row in rows}) != len(rows):
                raise ValueError("Duplicate block IDs")
            result = {row["id"]: row["text"].strip() for row in rows}
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise HumanizerError("The model returned an invalid rewrite payload.") from exc

        expected = {block.id for block in blocks}
        if set(result) != expected:
            raise HumanizerError("The model response did not contain every text block exactly once.")
        return result


def _parse_json_object(value: str) -> dict:
    text = value.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1])
        if text.lstrip().startswith("json"):
            text = text.lstrip()[4:].lstrip()
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("Expected a JSON object")
    return parsed

