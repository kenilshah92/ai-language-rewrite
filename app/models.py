from __future__ import annotations

from dataclasses import dataclass

import pymupdf as fitz


@dataclass(frozen=True)
class TextBlock:
    id: str
    page_index: int
    rect: fitz.Rect
    text: str
    font_name: str
    font_size: float
    color: tuple[float, float, float]
    align: int = fitz.TEXT_ALIGN_LEFT
    line_height: float | None = None
    context: str = ""
    layout_issue: str = ""

    @property
    def character_budget(self) -> int:
        return max(len(self.text), 12)


@dataclass(frozen=True)
class RewriteResult:
    block_id: str
    original: str
    rewritten: str
    status: str
    message: str = ""
