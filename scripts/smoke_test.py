from __future__ import annotations

from pathlib import Path
import tempfile

import pymupdf as fitz

from app.pdf_rewriter import extract_text_blocks, rewrite_pdf


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / "before.pdf"
        output = root / "after.pdf"
        document = fitz.open()
        page = document.new_page(width=720, height=405)
        page.draw_rect(fitz.Rect(0, 0, 720, 405), fill=(0.96, 0.95, 0.91))
        page.insert_textbox(fitz.Rect(70, 100, 650, 180), "AI becomes part of the operation, not a separate tool.", fontsize=22)
        document.save(source)
        document.close()

        document = fitz.open(source)
        blocks = extract_text_blocks(document)
        document.close()
        rewrite_pdf(source, output, {blocks[0].id: "AI works inside the operation, not beside it."})

        rendered = fitz.open(output)
        text = rendered[0].get_text()
        rendered.close()
        assert "AI works inside" in text
        print("Smoke test passed: PDF was rewritten and remains readable.")


if __name__ == "__main__":
    main()
