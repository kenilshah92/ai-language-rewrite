from pathlib import Path

import pymupdf as fitz

from app.pdf_rewriter import extract_text_blocks, rewrite_pdf


def _sample_pdf(path: Path) -> None:
    document = fitz.open()
    page = document.new_page(width=720, height=405)
    page.draw_rect(fitz.Rect(20, 20, 700, 385), color=(0.1, 0.4, 0.2), fill=(0.95, 0.97, 0.94))
    page.insert_textbox(fitz.Rect(60, 80, 660, 150), "Transforming businesses with intelligent operations", fontsize=24, fontname="helv", color=(0.05, 0.1, 0.06))
    page.insert_textbox(fitz.Rect(60, 180, 660, 250), "Every customer interaction becomes part of one connected workflow.", fontsize=15, fontname="helv", color=(0.2, 0.25, 0.2))
    document.save(path)
    document.close()


def test_rewrite_preserves_page_geometry(tmp_path):
    source = tmp_path / "source.pdf"
    output = tmp_path / "output.pdf"
    _sample_pdf(source)
    document = fitz.open(source)
    blocks = extract_text_blocks(document)
    document.close()
    replacements = {block.id: block.text.replace("businesses", "teams") for block in blocks}
    results = rewrite_pdf(source, output, replacements)

    before = fitz.open(source)
    after = fitz.open(output)
    assert before.page_count == after.page_count == 1
    assert before[0].rect == after[0].rect
    assert any(result.status == "rewritten" for result in results)
    before.close()
    after.close()


def test_embedded_font_survives_redaction(tmp_path):
    source = tmp_path / "embedded.pdf"
    output = tmp_path / "rewritten.pdf"
    with fitz.open() as document:
        page = document.new_page()
        page.insert_font(fontname="CustomFont", fontbuffer=fitz.Font("helv").buffer)
        page.insert_text((60, 100), "Original wording", fontname="CustomFont", fontsize=20)
        document.save(source)
    with fitz.open(source) as document:
        block = extract_text_blocks(document)[0]
    results = rewrite_pdf(source, output, {block.id: "Clear wording"})
    assert results[0].status == "rewritten"
    with fitz.open(output) as document:
        assert "Clear wording" in document[0].get_text()
        assert "Original wording" not in document[0].get_text()


def test_bold_fallback_is_valid():
    from app.pdf_rewriter import _fallback_font
    with fitz.open() as document:
        page = document.new_page()
        page.insert_text((60, 100), "Bold", fontname=_fallback_font("Unknown-Bold"))


def test_missing_glyph_keeps_original(tmp_path):
    source = tmp_path / "embedded.pdf"
    output = tmp_path / "rewritten.pdf"
    with fitz.open() as document:
        page = document.new_page()
        page.insert_font(fontname="CustomFont", fontbuffer=fitz.Font("helv").buffer)
        page.insert_text((60, 100), "Original wording", fontname="CustomFont", fontsize=20)
        document.save(source)
    with fitz.open(source) as document:
        block = extract_text_blocks(document)[0]
        pixels = document[0].get_pixmap().samples
    results = rewrite_pdf(source, output, {block.id: "New \U0001f984"})
    assert results[0].status == "skipped_missing_glyphs"
    with fitz.open(output) as document:
        assert document[0].get_pixmap().samples == pixels


def test_paragraph_lines_reflow_without_crossing_gap(tmp_path):
    from app.pdf_rewriter import _reflow_paragraphs
    source = tmp_path / "lines.pdf"
    output = tmp_path / "reflow.pdf"
    with fitz.open() as document:
        page = document.new_page(width=720, height=405)
        for y, text in [
            (80, "Customer demand grew quickly and the support team needed a better way to manage daily work."),
            (102, "The team reviewed each request and assigned it to the right person for a clear response."),
            (140, "This separate paragraph must remain separate from the paragraph above it."),
        ]:
            page.insert_text((50, y), text, fontsize=12)
        document.save(source)
    with fitz.open(source) as document:
        blocks = extract_text_blocks(document)
        replacements = {blocks[0].id: "Demand grew quickly and support needed a better process.",
                        blocks[1].id: "The team assigned requests to the right person."}
        grouped, values = _reflow_paragraphs(document, blocks, replacements)
        assert len(grouped) == 2
        assert grouped[1].text == blocks[2].text
        assert grouped[0].rect.x1 == max(b.rect.x1 for b in blocks[:2])
        assert grouped[0].line_height == 22 / 12
    rewrite_pdf(source, output, replacements)
    with fitz.open(output) as document:
        text = document[0].get_text()
        assert "Demand grew quickly and support needed a better process. The team" in text
        assert blocks[2].text in text


def test_overlapping_text_box_keeps_neighbor(tmp_path, monkeypatch):
    from dataclasses import replace
    import app.pdf_rewriter as engine
    source = tmp_path / 'overlap.pdf'
    output = tmp_path / 'safe.pdf'
    _sample_pdf(source)
    with fitz.open(source) as document:
        blocks = extract_text_blocks(document)
        pixels = document[0].get_pixmap().samples
    oversized = replace(blocks[0], rect=blocks[0].rect | blocks[1].rect)
    monkeypatch.setattr(engine, 'extract_text_blocks', lambda document: [oversized, blocks[1]])
    results = rewrite_pdf(source, output, {oversized.id: 'Short title'})
    assert results[0].status == 'skipped_overlap'
    with fitz.open(output) as document:
        assert document[0].get_pixmap().samples == pixels


def test_rewrite_preserves_numbers(tmp_path):
    source = tmp_path / 'numbers.pdf'
    output = tmp_path / 'safe-numbers.pdf'
    with fitz.open() as document:
        page = document.new_page()
        page.insert_text((60, 100), 'Existing 9-11 member team', fontsize=14)
        document.save(source)
    with fitz.open(source) as document:
        block = extract_text_blocks(document)[0]
    results = rewrite_pdf(source, output, {block.id: 'Existing team'})
    assert results[0].status == 'skipped_numbers'
    with fitz.open(output) as document:
        assert '9-11' in document[0].get_text()
