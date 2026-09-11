---
name: presentation-humanizer
description: Rewrite wording in presentation PDFs using this repository's humanizer prompt while preserving layout and all non-text content. Use for PDF deck rewrites; do not use for redesigns, factual edits, or scanned PDFs without a separate OCR decision.
---

# Presentation Humanizer

Use `settings/humanizer-prompt.md` as the authoritative style instruction.

When processing a presentation PDF:

1. Extract text with page and bounding-box metadata. Do not treat page images, charts, shapes, or vector artwork as editable content.
2. Rewrite coherent text blocks, not isolated words. Preserve facts, names, figures, citations, URLs, and meaning.
3. Constrain each rewrite to the original text box. Prefer a shorter natural rewrite over reducing type size.
4. Replace text in place while retaining the original box position, dominant font properties, alignment, and color as closely as the PDF permits.
5. If a rewrite cannot fit above the configured minimum scale, keep the original block and report it. Never silently clip, overlap, move, or redesign content.
6. Validate that page count and page dimensions are unchanged. Render before and after PDFs and inspect for clipping, overlap, missing glyphs, or changed non-text content.

PDFs with outlined text or scanned text may have no editable text layer. Report that limitation instead of invoking OCR automatically.

