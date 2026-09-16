# Product

AI Language Rewrite is a private document-copyediting app for an owner and a small trusted team (currently 2–3 people). Users upload documents, choose a configured model, and download rewritten files and JSON decision reports. Hosting is on Render; GitHub stores deployment source, not the running app.

## Supported inputs

| Input | Editable unit | Preservation and limits |
| --- | --- | --- |
| PDF with an editable text layer | Extracted text blocks; qualifying adjacent wide prose lines merged before generation | Preserve page geometry and non-text artwork; render accepted replacements in the original text region. Skip unsafe changes. No OCR. |
| Word `.docx` | Adjacent equal-style text runs within supported paragraphs | Retain XML properties and unedited package assets. Protected structures remain original. Replacements cannot exceed the original group character count. Word may repaginate. |
| UTF-8 `.txt` | Each nonblank line | Preserve BOM, original newline delimiters, indentation, trailing whitespace and blank lines. No rich formatting exists in TXT. |

Legacy `.doc`, `.docm`, PPTX, RTF, HTML and Markdown extensions are rejected. A scanned PDF with no editable text fails; there is no separate OCR or conversion service. A partly scanned PDF may have only its text layer processed. Default upload limit is 50 MiB per file; that is an admission limit, not a guarantee every document of that size is processable.

## Rewrite contract

The authoritative editorial instructions live in `settings/humanizer-prompt.md`. They request substantive copyediting of inflated or repetitive prose, direct language, natural sentence structure, and preservation of meaning, voice, facts, names, numbers, product terms, URLs and citations. Clear labels need not change. Attributed quotations stay verbatim; unattributed slogans can be rewritten. Text inside uploaded files is data, not system instructions.

The prompt includes guidance adapted from Wikipedia's Signs of AI writing. The app reads this local guidance; it does not fetch the article during each job. It makes no AI-detector guarantee. Model choice changes generation, not preservation rules.

PDF rewriting separates generation from fit checks and final rendering. Up to two targeted repair rounds address rejected proposals without intentionally retreating to proofreading-only behavior. The final report distinguishes unchanged text from preservation skips. DOCX and TXT currently have one generation pass and no repair loop.

## Formatting: intended contract versus current enforcement

PDF page count, dimensions, images, vector graphics, colors and element positions are intended invariants. The renderer uses text-only redaction flags and fit checks, and runtime validation compares page count and dimensions. It does not perform a complete visual comparison on every job. Fonts fall back to Base14 if extraction fails; size can shrink to the configured floor (default 85%). The text rectangle receives a bottom allowance of 0.45 times the original font size. These are current implementation compromises, not a promise of exact typography.

Mixed-style and disconnected/non-left-aligned multiline blocks are conservatively protected. Overlap checks and missing-glyph checks also reject changes. Known overflow stays original and is reported; an unexpected insertion overflow causes a fresh render from the original with that block kept unchanged and reported. PDF layout needs human review, especially with complex diagrams or tight spacing.

DOCX preserves style definitions and package structure, not fixed pagination. Fields, review markup, content controls, text boxes, paragraphs containing artwork, hyperlinks and fixed-height rows are protected by conservative rules. Shorter text can still move flow-positioned objects. TXT preserves line structure but can change spacing inside a rewritten line.

Numeric tokens, HTTP(S) URLs, email addresses and numbered citation patterns have deterministic checks. Names, meaning, attribution and other facts rely on the prompt and human review; there is no semantic fact checker.

## Privacy and audience

A shared HTTP Basic login protects the hosted app. There are no separate accounts or per-user file permissions. Files remain on the processing machine: the user's Mac locally, the Render instance when hosted. Only extracted text, context and repair instructions go to OpenAI. Reports contain document text and the prompt snapshot, so treat them as confidential. There is no application telemetry or external object storage.
