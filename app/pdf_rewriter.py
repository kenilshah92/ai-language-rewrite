from __future__ import annotations

from collections import Counter
from dataclasses import asdict, replace
from pathlib import Path
import re

import pymupdf as fitz

from app.models import RewriteResult, TextBlock
from app.document_rewriter import preservation_issue


_MEANINGFUL_TEXT = re.compile(r"[A-Za-z\u00C0-\uFFFF]{2,}")


def extract_text_blocks(document: fitz.Document) -> list[TextBlock]:
    blocks: list[TextBlock] = []
    for page_index, page in enumerate(document):
        page_dict = page.get_text("dict", flags=fitz.TEXTFLAGS_TEXT)
        text_block_index = 0
        for raw_block in page_dict.get("blocks", []):
            if raw_block.get("type") != 0:
                continue
            lines = raw_block.get("lines", [])
            spans = [span for line in lines for span in line.get("spans", []) if span.get("text")]
            text = "\n".join(
                "".join(span.get("text", "") for span in line.get("spans", [])).strip()
                for line in lines
            ).strip()
            if not spans or not text or not _MEANINGFUL_TEXT.search(text):
                continue

            dominant = _dominant_span(spans)
            rect = fitz.Rect(raw_block["bbox"])
            layout_issue = _layout_issue(lines, spans)
            blocks.append(
                TextBlock(
                    id=f"p{page_index + 1}-b{text_block_index + 1}",
                    page_index=page_index,
                    rect=rect,
                    text=text,
                    font_name=str(dominant.get("font", "Helvetica")),
                    font_size=float(dominant.get("size", 12.0)),
                    color=_pdf_color(int(dominant.get("color", 0))),
                    layout_issue=layout_issue,
                )
            )
            text_block_index += 1
    return blocks


def _layout_issue(lines: list[dict], spans: list[dict]) -> str:
    """Reject blocks whose runs cannot safely share one text box/style."""
    styles = {(s.get('font'), round(s.get('size', 12), 1), s.get('color'))
              for s in spans if s.get('text', '').strip()}
    if len(styles) > 1:
        return 'Mixed font styles within one PDF block require preserving the original text.'
    rects = [fitz.Rect(line['bbox']) for line in lines if line.get('spans')]
    if any(b.y0 <= a.y0 or abs(b.x0 - a.x0) > 2 for a, b in zip(rects, rects[1:])):
        return 'Separated or non-left-aligned text runs require preserving their original positions.'
    return ''


def rewrite_pdf(
    input_path: Path,
    output_path: Path,
    replacements: dict[str, str],
    min_font_scale: float = 0.85,
    *, prepared_blocks: list[TextBlock] | None = None, dry_run: bool = False,
) -> list[RewriteResult]:
    document = fitz.open(input_path)
    original_page_sizes = [(page.rect.width, page.rect.height) for page in document]
    if prepared_blocks is None:
        blocks = extract_text_blocks(document)
        blocks, replacements = _reflow_paragraphs(document, blocks, replacements)
    else:
        blocks = prepared_blocks
    results: list[RewriteResult] = []

    planned: list[tuple[TextBlock, str, float, str, bytes | None]] = []
    for block in blocks:
        replacement = replacements.get(block.id, block.text).strip()
        if not replacement:
            results.append(RewriteResult(block.id, block.text, block.text, "skipped_empty", "Replacement was empty."))
            continue
        if replacement == block.text:
            results.append(RewriteResult(block.id, block.text, block.text, "unchanged"))
            continue

        if block.layout_issue:
            results.append(RewriteResult(block.id, block.text, block.text,
                                         'skipped_complex_layout', block.layout_issue))
            continue

        number_pattern = r"\d+(?:[.,]\d+)*"
        if Counter(re.findall(number_pattern, block.text)) != Counter(re.findall(number_pattern, replacement)):
            results.append(RewriteResult(
                block.id, block.text, block.text, "skipped_numbers",
                "Rewrite changed numeric content; kept the original text.",
            ))
            continue

        issue = preservation_issue(block.text, replacement)
        if issue:
            results.append(RewriteResult(block.id, block.text, block.text, "skipped_preservation", issue))
            continue

        # Some PDFs group distant labels in one bounding box. Redacting that
        # box would erase neighboring text which belongs to another block.
        if any(other.id != block.id and other.page_index == block.page_index
               and (block.rect & other.rect).get_area() > 0.1 for other in blocks):
            results.append(RewriteResult(
                block.id, block.text, block.text, "skipped_overlap",
                "Original text box overlaps another text block; kept original to protect neighboring text.",
            ))
            continue

        font_alias, font_buffer = _font_for_block(document, block, replacement)
        if font_buffer:
            font = fitz.Font(fontbuffer=font_buffer)
            missing = sorted({char for char in replacement if not char.isspace() and not font.has_glyph(ord(char))})
            if missing:
                results.append(RewriteResult(
                    block.id, block.text, block.text, "skipped_missing_glyphs",
                    "Embedded font lacks replacement characters: " + "".join(missing),
                ))
                continue
        page = document[block.page_index]
        if font_buffer:
            page.insert_font(fontname=font_alias, fontbuffer=font_buffer)
        size = _largest_fitting_size(page, block, replacement, font_alias, min_font_scale)
        if size is None:
            results.append(
                RewriteResult(
                    block.id,
                    block.text,
                    block.text,
                    "skipped_overflow",
                    "Rewrite could not fit inside the original text box.",
                )
            )
            continue
        planned.append((block, replacement, size, font_alias, font_buffer))

    if dry_run:
        results.extend(RewriteResult(b.id, b.text, text, "rewritten") for b, text, _, _, _ in planned)
        document.close()
        return sorted(results, key=lambda result: result.block_id)

    for block, _, _, _, _ in planned:
        page = document[block.page_index]
        page.add_redact_annot(block.rect, fill=None)
    for page_index in range(document.page_count):
        page = document[page_index]
        page.apply_redactions(
            images=fitz.PDF_REDACT_IMAGE_NONE,
            graphics=fitz.PDF_REDACT_LINE_ART_NONE,
            text=fitz.PDF_REDACT_TEXT_REMOVE,
        )
        document.reload_page(page)

    for block, replacement, size, font_alias, font_buffer in planned:
        page = document[block.page_index]
        # Redaction can discard unused font resources. Restore before writing.
        if font_buffer:
            page.insert_font(fontname=font_alias, fontbuffer=font_buffer)
        remaining = page.insert_textbox(
            _text_rect(block),
            replacement,
            fontname=font_alias,
            fontsize=size,
            color=block.color,
            align=block.align,
            lineheight=block.line_height,
            overlay=True,
        )
        if remaining < -0.01:
            document.close()
            raise RuntimeError(f"Unexpected overflow while writing {block.id}")
        results.append(RewriteResult(block.id, block.text, replacement, "rewritten"))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    document.save(output_path, garbage=4, deflate=True)
    document.close()

    _validate_structure(input_path, output_path, original_page_sizes)
    return sorted(results, key=lambda result: result.block_id)


def _reflow_paragraphs(
    document: fitz.Document, blocks: list[TextBlock], replacements: dict[str, str],
    *, force: bool = False,
) -> tuple[list[TextBlock], dict[str, str]]:
    """Join adjacent prose lines, preserving paragraph gaps and column boundaries."""
    merged: list[TextBlock] = []
    replacements = dict(replacements)
    index = 0
    while index < len(blocks):
        first = blocks[index]
        group = [first]
        page_width = document[first.page_index].rect.width
        # Wide, single-line body text is safe to reflow. Labels, headings,
        # bullets and narrow columns retain their independent layout.
        if ("\n" not in first.text and first.rect.width > page_width * 0.55
                and len(first.text) > 65 and not _list_line(first.text)):
            while index + len(group) < len(blocks):
                previous = group[-1]
                candidate = blocks[index + len(group)]
                gap = candidate.rect.y0 - previous.rect.y1
                if not (
                    candidate.page_index == first.page_index
                    and "\n" not in candidate.text
                    and not _list_line(candidate.text)
                    and abs(candidate.rect.x0 - first.rect.x0) < 1
                    and candidate.font_name == first.font_name
                    and abs(candidate.font_size - first.font_size) < 0.1
                    and candidate.color == first.color
                    and 0 <= gap <= first.font_size * 0.6
                    and previous.rect.width > page_width * 0.55
                ):
                    break
                group.append(candidate)
        if len(group) > 1 and (force or any(replacements.get(b.id, b.text) != b.text for b in group)):
            rect = fitz.Rect(first.rect)
            for member in group[1:]:
                rect |= member.rect
            leading = (group[1].rect.y0 - first.rect.y0) / first.font_size
            merged.append(replace(first, rect=rect, text=" ".join(b.text for b in group), line_height=leading,
                                  layout_issue=next((b.layout_issue for b in group if b.layout_issue), '')))
            replacements[first.id] = " ".join(replacements.get(b.id, b.text).strip() for b in group)
        else:
            merged.extend(group)
        index += len(group)
    return merged, replacements


def prepare_pdf_blocks(document: fitz.Document) -> list[TextBlock]:
    """Stable paragraph units shared by generation, repair and final rendering."""
    blocks, _ = _reflow_paragraphs(document, extract_text_blocks(document), {}, force=True)
    contextual = []
    for i, block in enumerate(blocks):
        nearby = blocks[max(0, i - 1):i + 2]
        context = "\n".join(b.text[:500] for b in nearby if b.page_index == block.page_index and b.id != block.id)
        contextual.append(replace(block, context=context))
    return contextual



def repair_constraints(document: fitz.Document, block: TextBlock, proposed: str) -> dict:
    _, buffer = _font_for_block(document, block, proposed)
    constraints = {"maximum_characters": block.character_budget}
    if buffer:
        font = fitz.Font(fontbuffer=buffer)
        chars = set(chr(i) for i in range(32, 127)) | set(block.text) | set(proposed)
        constraints["available_characters"] = "".join(sorted(c for c in chars if c.isspace() or font.has_glyph(ord(c))))
    return constraints


def _list_line(text: str) -> bool:
    return bool(re.match(r"^(?:[•●▪*-]\s|\d+[.)]\s)", text.strip()))


def report_to_dict(results: list[RewriteResult]) -> dict:
    counts = Counter(item.status for item in results)
    return {
        "summary": dict(counts),
        "blocks": [asdict(item) for item in results],
    }


def _dominant_span(spans: list[dict]) -> dict:
    return max(spans, key=lambda span: len(str(span.get("text", ""))))


def _pdf_color(value: int) -> tuple[float, float, float]:
    red, green, blue = fitz.sRGB_to_rgb(value)
    return red / 255, green / 255, blue / 255


def _font_for_block(document: fitz.Document, block: TextBlock, text: str = "") -> tuple[str, bytes | None]:
    normalized = block.font_name.split("+")[-1].lower().replace(" ", "").replace("-", "")
    candidates = []
    for font in document[block.page_index].get_fonts(full=True):
        xref = font[0]
        names = [str(item).split("+")[-1].lower().replace(" ", "").replace("-", "") for item in font[3:6]]
        if normalized not in names or xref <= 0:
            continue
        try:
            _, extension, _, buffer = document.extract_font(xref)
        except RuntimeError:
            continue
        if buffer and extension not in {"n/a", ""}:
            embedded = fitz.Font(fontbuffer=buffer)
            missing = sum(not embedded.has_glyph(ord(c)) for c in set(text) if not c.isspace())
            candidates.append((missing, xref, buffer))
    if candidates:
        _, xref, buffer = min(candidates, key=lambda item: item[0])
        return f"RewriteFont{xref}", buffer
    return _fallback_font(block.font_name), None


def _fallback_font(name: str) -> str:
    lower = name.lower()
    if "courier" in lower:
        return "courier-bold" if "bold" in lower else "courier"
    if "times" in lower or "serif" in lower:
        return "times-bold" if "bold" in lower else "times-roman"
    return "hebo" if "bold" in lower else "helv"


def _largest_fitting_size(
    page: fitz.Page,
    block: TextBlock,
    text: str,
    font_name: str,
    min_font_scale: float,
) -> float | None:
    minimum = block.font_size * min_font_scale
    size = block.font_size
    target_rect = _text_rect(block)
    while size + 0.001 >= minimum:
        shape = page.new_shape()
        remaining = shape.insert_textbox(
            target_rect,
            text,
            fontname=font_name,
            fontsize=size,
            color=block.color,
            align=block.align,
            lineheight=block.line_height,
        )
        if remaining >= -0.01:
            return round(size, 2)
        size -= max(0.25, block.font_size * 0.025)
    return None


def _text_rect(block: TextBlock) -> fitz.Rect:
    # PDF extraction returns the painted glyph bounds, not the authoring text box.
    # Add one conservative descender/line-spacing allowance without moving the
    # visible top-left anchor or widening into neighboring content.
    rect = fitz.Rect(block.rect)
    rect.y1 += block.font_size * 0.45
    return rect


def _validate_structure(
    input_path: Path,
    output_path: Path,
    expected_sizes: list[tuple[float, float]],
) -> None:
    original = fitz.open(input_path)
    rewritten = fitz.open(output_path)
    try:
        if rewritten.page_count != original.page_count:
            raise RuntimeError("Page count changed during rewrite.")
        actual_sizes = [(page.rect.width, page.rect.height) for page in rewritten]
        if actual_sizes != expected_sizes:
            raise RuntimeError("Page dimensions changed during rewrite.")
    finally:
        original.close()
        rewritten.close()
