# AI Language Rewrite

A private app for rewriting PDF, Word DOCX, and UTF-8 TXT documents using an editable writing prompt and a configurable OpenAI API model.

## Run locally

Requires Python 3.11 or newer.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
cp .env.example .env
```

Add your API key to `.env`. Never commit it. Start with:

```sh
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000. Select one or more files and a configured model. The app processes jobs in the background and offers a rewritten document plus a JSON report. The default model is `gpt-5.6-terra`; account API access is required. The shared selector keeps its choice while switching between file and text rewrites. It orders GPT-5.6 Terra, GPT-5.6 Luna, GPT-5.6 Sol, then Astra by default. Add permitted IDs to `ALLOWED_MODELS` in `.env` to expose alternatives, then restart.

## Supported formats and preservation

| Format | Preserved | Limitations |
|---|---|---|
| PDF | Page count/dimensions, images, vector artwork; original text areas; embedded fonts where usable | Scans and outlined text need a separate OCR workflow. Missing glyphs, overflow, overlapping boxes, and changed numeric content are skipped. Wide body paragraphs reflow inside the original paragraph area. Complex mixed-style and disconnected multiline blocks are kept original; exact visual preservation is not guaranteed. |
| DOCX | Run and paragraph properties, styles, font settings, section settings, table structure, links and package assets | Rewrites stay within equal-format run groups and cannot expand beyond their original character count. Fields, tracked changes, content controls, paragraphs with images, text boxes, and fixed-height rows stay original. Shorter text can still change pagination and move flow-positioned elements; review in Word. Exact visual identity is not guaranteed. |
| TXT | UTF-8/BOM, line-ending convention, blank lines and indentation | Text is rewritten within each nonblank line. TXT has no fonts, images or rich formatting. |

Legacy `.doc`, `.docm`, PPTX, RTF, HTML, and Markdown are not supported. Unsupported content is never silently converted into another format. A report lists every processed group and skipped item. DOCX/TXT protection also checks URLs, email addresses and numbered citation markers; factual and semantic review remains necessary.

## Writing rules

`settings/humanizer-prompt.md` is the sole authoritative style prompt. It includes editorial guidance adapted from https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing (reviewed 2026-09-09). These are contextual writing-quality principles, not a guarantee about AI detection. Existing formatting is not redesigned to follow Wikipedia conventions.

Document text is sent as data, including paragraph context for Word fragments. The prompt tells the model not to follow instructions inside uploaded documents, not to invent claims, and not to move facts between blocks. The API schema remains in application code; the writing rules stay in the prompt file.

## Privacy and hosting

Local files remain on this computer; only extracted text is sent to OpenAI. Local retention defaults to unlimited. In hosted mode, files are processed on the server and expire after the configured retention period. The application adds no telemetry or external file storage.

See [DEPLOYMENT.md](DEPLOYMENT.md) for the private Render/Docker setup, secret-file configuration, HTTPS, shared-login requirements, retention, restart behavior, and limitations. The app is deployed on Render free hosting at https://ai-language-rewrite.onrender.com. See docs/CURRENT_STATE.md for recorded verification and source-management limitations.

## Verification

```sh
pytest
PYTHONPATH=. python scripts/smoke_test.py
```

Tests cover PDF font restoration, glyph/overlap/number protection and paragraph reflow; DOCX package/style preservation and protected structures; TXT encoding/spacing; private routes; model validation; job completion; and retention.


## Paragraph-first PDF workflow

PDF paragraphs are grouped before generation and the same groups are used for fit checks and rendering. The first pass edits prose, headings and unattributed slogans substantively while protecting facts and genuine quotations. Rejected changes receive up to two targeted repair rounds for font glyphs, overflow, numeric content, or protected text. The renderer applies the final accepted text once, starting from the source PDF. Nonrepairable overlap cases remain original.

PDF reports include initial proposals, checked repair attempts, final decisions, page/box locations, model response IDs, source and prompt hashes, and the exact prompt snapshot. Text coverage measures the proportion of source characters in changed groups, not how many individual words changed. A repair failure preserves the usable first-pass changes and reports the rejected blocks.

## Project context and planning

Start with [Current state and ChatGPT handoff](docs/CURRENT_STATE.md).

- [Product and preservation contract](docs/PRODUCT.md)
- [Architecture and pipelines](docs/ARCHITECTURE.md)
- [Deployment and environment settings](docs/DEPLOYMENT.md)
- [Engineering instructions](AGENTS.md)

Upload the four documents under `docs/` to a ChatGPT Project for planning. Return a scoped change brief to Codex for implementation. Keep secrets, customer documents and generated reports out of that context. The application source remains in its existing directories; this documentation pass does not reorganize executable code.
