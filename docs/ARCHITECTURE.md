# Architecture

Inspected implementation: app version `0.3.0`, PDF pipeline `paragraph-first-v3`.

## Components

| Path | Responsibility |
| --- | --- |
| `app/main.py` | FastAPI routes, Basic authentication, upload validation, in-memory jobs, thread pool, cleanup, report downloads |
| `app/static/index.html` | Single HTML page with inline CSS and vanilla JavaScript; no frontend framework or build step |
| `app/config.py` | Environment loading and immutable settings instantiated at import |
| `app/humanizer.py` | Prompt snapshot, OpenAI Responses request, JSON response validation |
| `app/models.py` | PDF text-block metadata and shared rewrite-result records |
| `app/pdf_pipeline.py` | Paragraph preparation, generation, bounded repairs, final PDF render, audit metadata |
| `app/pdf_rewriter.py` | PyMuPDF extraction, grouping, font selection, preservation/fit decisions, redaction and insertion |
| `app/document_rewriter.py` | DOCX ZIP/XML processing, TXT processing, shared token-preservation checks |
| `settings/humanizer-prompt.md` | Single source of editorial instructions |

Runtime dependencies are FastAPI, Uvicorn, python-multipart, PyMuPDF, OpenAI Python SDK, python-dotenv and Pydantic. DOCX uses Python `zipfile` and `xml.dom.minidom`, not python-docx or LibreOffice. Tests use pytest/httpx. Version ranges are in requirements files; there is no lockfile.

## Request lifecycle

1. The page loads `/api/config`, populates the model selector, and submits one multipart request per selected file. Multiple files submit concurrently.
2. `POST /api/rewrite` validates extension and configured model, reserves a job slot, streams the upload in 1 MiB chunks to disk, rejects empty/oversize files, and returns HTTP 202 with a job/status URL.
3. A two-thread executor processes jobs. At most eight jobs may be uploading, queued or processing. State is a process-local dictionary guarded by a thread lock, not a durable queue.
4. The worker generates the output and report, then marks completion or a sanitized failure. The page polls every two seconds. Three consecutive polling failures stop browser polling; server work may still continue.
5. Users download the file and JSON report. Reloading the page does not restore a job list.

| Route | Purpose | Authentication |
| --- | --- | --- |
| `GET /` | HTML UI | Required in hosted mode |
| `GET /api/config` | Model choices, file limit, storage settings | Required in hosted mode |
| `POST /api/rewrite` | Upload `file` and optional `model` | Required in hosted mode |
| `GET /api/jobs/{job_id}` | Status/result links | Required in hosted mode |
| `GET /api/download/{filename}` | Output/report file | Required in hosted mode |
| `GET /api/health` | `{"status":"ok"}` | Public |

OpenAPI/docs routes are disabled. Responses set no-store, nosniff and no-referrer headers. POST requests with an Origin whose netloc differs from Host are rejected. Missing Origin is allowed. Authentication compares credentials using `secrets.compare_digest`.

## PDF pipeline

PyMuPDF extracts raw text blocks and span style/geometry. Blocks require meaningful alphabetic text; numeric-only blocks may not be represented as editable units. The longest span supplies the dominant font/color/size. Mixed-style runs or non-left-aligned/disconnected multiline arrangements receive a layout issue.

Qualifying adjacent wide single-line prose is merged using width, length, list-marker, font, color, x-position and vertical-gap heuristics. This is heuristic paragraph detection, not recovery of authoring text boxes. Each prepared unit receives up to two neighboring same-page snippets, capped at 500 characters each. Generation and rendering use the same units.

The first proposal set is dry-run checked. Empty text, numeric/URL/email/citation changes, overlaps, complex layout, unavailable glyphs and failure to fit produce explicit decisions. Embedded fonts are matched by normalized names and chosen by glyph coverage; Base14 is a fallback. Fit tests reduce font size in steps down to the configured minimum. Original boxes are checked for overlap; the extra bottom allowance is not a complete collision detector.

At most two repair calls target empty, preservation, numeric, glyph and overflow failures. Overflow repair asks for 80% of the proposed length. Glyph repair supplies available characters. Overlap and complex-layout skips are not repaired. Optional repair failures retain usable proposals and add a report warning. Identical repair proposals terminate early.

Final rendering reopens the original, redacts accepted text regions while preserving images/vector graphics via PyMuPDF flags, reloads pages, restores embedded fonts, and inserts accepted text once. Page count/dimensions are validated afterward. The application does not raster-compare every result.

PDF reports include original/final text, status/reason, initial proposal, checked attempts, page/rectangle, model, response IDs, prompt snapshot/hash, source hash, repair errors and rewritten-source-character coverage. Coverage counts all source characters in changed blocks; it is not word edit distance. Audit history records checked changes and may omit a no-op repair response.

## DOCX and TXT reconstruction

DOCX validates ZIP members (no duplicates, at most 10,000 entries, at most 150 MiB total declared expanded size), requires `word/document.xml`, rejects VBA/signature parts, and rejects entity/DOCTYPE declarations in parsed XML. It processes document, numbered headers/footers, footnotes and endnotes. Eligible equal-property text nodes are grouped; surrounding paragraph text is model context. Protected paragraphs/hyperlinks are reported. Accepted replacement text is written to the group's first node and later nodes emptied, retaining runs/properties. Unchanged package parts are verified byte-identical. XML serialization can change edited XML byte representation. There is no Word rendering or pagination verification.

TXT decodes UTF-8 with optional BOM, rejects NUL bytes, and separates content from exact newline delimiters. Each nonblank stripped line is an input block. Reconstruction retains outer whitespace and delimiters. Empty replacements, new tabs/newlines and protected-token changes are rejected; TXT has no length-expansion limit.

DOCX/TXT reports have summary, decisions, model, format, prompt snapshot/hash and initial proposals. DOCX adds a pagination warning. They do not have the full PDF repair/source-hash audit.

## OpenAI usage

`Humanizer` snapshots the local prompt once per job. `OpenAI(timeout=600.0, max_retries=1)` calls `client.responses.create` with model, editorial instructions plus a JSON-output contract, and serialized blocks (ID, text, character budget, context, repair object). The whole eligible document is sent in one initial request; there is no token-budget batching. The app validates string fields, duplicate IDs and exact ID coverage after parsing; it does not use a strict API JSON schema. There is no explicit reasoning-effort, temperature, maximum-output-token or `store` setting. Provider retention defaults are not overridden by this implementation.

API key presence/model permissions/billing are not verified by the health endpoint. Model IDs in configuration are options, not proof of account availability. Initial API failure fails the job; optional PDF repair failure does not discard successful edits.

## Configuration and files

See [DEPLOYMENT.md](DEPLOYMENT.md) for the complete environment table. Process environment takes precedence over `/etc/secrets/.env`, which takes precedence over root `.env` because dotenv loading does not override existing values. Settings and directories are initialized at import; restart after changes.

Uploads and outputs use UUID-prefixed sanitized filenames under `DATA_DIR/uploads` and `DATA_DIR/output`. Failed jobs remove output/report, but their source remains until cleanup. Cleanup runs at startup and every five minutes, using file mtime and job creation time, exempting active job prefixes. Local retention defaults to unlimited; hosted retention must be positive. Restarts lose all job state; Render's ephemeral disk also loses files on replacement/redeploy. There is no database, object store, scheduler service, cancellation API, persistent job history or per-person isolation.
