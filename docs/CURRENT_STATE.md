# Current state

## 2026-09-17: free-text rewrite mode and clearer rewrite flow

The interface now provides a compact Files/Text mode switch. Each mode owns one clear primary action: **Rewrite selected files** or **Rewrite text**. Text mode accepts up to 20,000 characters, sends the selected model to `POST /api/rewrite-text`, shows an in-progress spinner and status while the request runs, shows errors in context, and returns an editable result with copy and reset controls. File processing retains its existing per-file upload, queue, processing and completion status panels.
The progress and result panels explicitly apply `display: none` while their `hidden` attribute is present, preventing a visible working state before a request or after it completes.

Validation: `python -m pytest -q -p no:cacheprovider` — **27 passed**. `PYTHONPATH=. python scripts/smoke_test.py` is run as part of this release check. This commit is intended for Render auto-deploy; a fresh hosted text rewrite remains a manual acceptance check after the deployment reaches Live.

## 2026-09-16: final PDF insertion overflow fix

Reproduced the Gully Labs failure using saved model proposals: the previous renderer raised `Unexpected overflow while writing p2-b30`. Fit testing rounded the accepted font size before final insertion. The renderer now uses the exact tested size. If a final insertion still overflows, it discards the tentative render and rebuilds from the original without that replacement, reporting `skipped_final_overflow`; no additional model calls are made. Each retry removes failed blocks, so retries are bounded.

Validation: 25 tests and the PDF smoke check pass. Replaying the saved Gully Labs proposals through the normal pipeline completes with 102 rewritten blocks and 21 protected complex-layout blocks. All 10 page geometries, images and vector drawings match; accepted replacement text is present. This replay uses no paid API request. Hosted logs were not available during diagnosis, so the exact hosted error is not independently confirmed. Deployment and a fresh hosted upload remain separate checks.


Inspection date: 2026-09-11. Application version: 0.3.0. This is a documentation/source-organization pass; application code and prompt are unchanged. Deployment packaging now builds directly from source, and render.yaml selects the free tier.

## Working implementation

- PDF, DOCX and UTF-8 TXT upload, model selection, background jobs, output and JSON-report downloads.
- Paragraph-first PDF generation, two bounded repair rounds, fit/preservation checks, one final render from the original, detailed PDF audit metadata.
- Conservative DOCX run-group editing with package preservation; TXT line/whitespace reconstruction.
- Shared Basic authentication in hosted mode, 50 MiB default upload limit, eight admitted active jobs and two processing threads.
- File expiration, sanitized filenames and API error messages, private response headers, cross-origin POST check.
- Local editable humanizer prompt incorporating Wikipedia writing guidance. No live wiki fetch or semantic fact checker.

## Verification evidence

Re-run during this inspection: `python -m pytest -q` — **23 passed** (7 dependency deprecation warnings); `PYTHONPATH=. python scripts/smoke_test.py` — **passed**. The smoke test creates a small synthetic PDF, rewrites it and checks readable output text without OpenAI.

Tests cover API routes, authentication/startup gating, asynchronous TXT flow/download, invalid format/model/origin rejection, retention protection for active jobs; DOCX asset/style/run/protected-structure retention and expansion rejection; TXT encoding/spacing; PDF geometry, fonts, glyphs, overlap, numbers, paragraph grouping, repair failure/bounds and complex-layout preservation; model ID mapping and duplicate-response rejection. These are mostly small synthetic fixtures, not a comprehensive real-document or load suite. API calls are mocked; no paid model calls were made for this documentation pass.

Prior deployment evidence: Render built and started release commit `7e5179bbde30680006010f61e71020a738020cd4`, health returned 200, and an unauthenticated app request returned 401. The owner now reports the hosted app works. A fresh authenticated hosted PDF/DOCX/TXT acceptance suite was not run during this inspection. Earlier local customer-deck outputs/reports exist under ignored output storage; they are not portable test fixtures or proof of universal layout correctness.

## Local and remote setup

Local root: `/Users/Kenil/Documents/ChatGPT/ai-language-rewrite`. The `.venv` reports Python 3.14.6. The project was moved from Downloads to Documents/ChatGPT. Invoke `.venv/bin/python -m ...` directly until the moved virtual environment is recreated, because activation/console scripts can retain the old path. A local `.env` exists; its values are intentionally excluded from documentation. Docker is absent from PATH. Presence of a local environment does not establish that the localhost server is currently running.

The full project is now a Git working tree on main, tracking origin/main. The cleanup is based on the original remote commit 7e5179bbde30680006010f61e71020a738020cd4 and adds ordinary source files and documentation. The archived release and wrapper Dockerfile are replaced by the direct-source build. History is preserved. Use git log -1 to identify the cleanup commit after it is created.

Deployment URL: https://ai-language-rewrite.onrender.com. Recorded live configuration: free tier, Singapore, one Docker web service, ephemeral files and shared login. render.yaml now matches the free-tier choice. No custom domain or database. Deployment success for this cleanup must be checked separately from its commit; earlier live acceptance evidence is recorded above.

## Documentation delivery and Git workflow

AGENTS.md and docs/PRODUCT.md, ARCHITECTURE.md, CURRENT_STATE.md and DEPLOYMENT.md provide portable context. README links to them. Application and prompt files were byte-compared with source.zip from the original GitHub commit and match. Secrets, local tool settings and generated customer files are excluded from Git.

The owner requests one local/remote main branch and one cleanup commit directly on main. No PR is created for this change. Future PRs require temporary source branches only if requested. Fetch and inspect upstream changes before committing; do not force-push. A documentation-only planning bundle is generated at output/chatgpt-project-context.zip and is not tracked.

## Known issues and technical debt

1. The legacy packaging helper remains for historical use and omits docs; normal releases must use the ordinary source tree. Render auto-deploy must be checked after each main push.
2. PDF preservation is conservative but not a universal exact-layout guarantee. Font fallback, font shrink and bottom allowance can alter typography; complex blocks are skipped. Runtime post-validation checks only page geometry, not all images, vectors, content positions or visual collisions.
3. Names, meaning and attribution are prompt-protected, not semantically validated. Numeric-token equality alone cannot prove factual equivalence.
4. DOCX may repaginate. Mixed-style constraints reduce rewrite freedom; no Word render verification or targeted DOCX/TXT repair exists.
5. All eligible blocks go in one model request. There is no context/token batching, output-token cap, cost estimator, per-user budget or complete model capability validation.
6. Shared login has no per-user isolation. Job state is volatile; no cancellation, resume, durable queue or page-refresh job recovery. Expiry is approximate and paused with the instance.
7. Free-tier memory/CPU and maximum-size/concurrent-document processing have not been load-tested. ZIP expanded-size limits are not general PDF resource limits.
8. Dependency ranges are broad and unlocked; local Python differs from Docker Python. No CI workflow, formatter/linter configuration or production dependency lockfile was found.
9. PDF report coverage is changed-block source-character coverage, not edit distance. Repair audit can omit unchanged repair responses; other formats have less metadata than PDF.
10. Tests do not cover every preservation branch, real-world DOCX pagination, every allowed model, deployment-secret parsing, or provider errors end-to-end. Health does not test API key, billing or model access.

## Remaining work and deployment readiness

The small-team app is already deployed. This change normalizes source management without changing rewrite behavior. Remaining release verification: confirm Render builds the direct-source Dockerfile and passes startup/health checks after the main push. A fresh authenticated rewrite acceptance suite remains separate from unit-test evidence.

Future product changes (PPTX/OCR, larger files, better mixed-style rewrites, durable jobs or individual accounts) require a separate scope and acceptance criteria. Do not silently implement them as documentation cleanup. Before expanding use, prioritize measured capacity, reproducible dependencies and repeatable visual regression fixtures.

## Handoff for ChatGPT / ChatGPT Work

Use this file, PRODUCT.md, ARCHITECTURE.md and DEPLOYMENT.md as planning context. The app is a Python/FastAPI document rewriter with a plain HTML/JavaScript frontend, OpenAI Responses API, PyMuPDF PDF reconstruction, conservative DOCX XML edits and line-based TXT edits. It runs on Render free hosting for 2–3 trusted people. Preserve substantive paragraph-first rewriting and the authoritative local prompt; known unsafe edits must remain original with reasons. Exact visual preservation is a goal with documented limits, not a proven universal guarantee.

Planning sessions should produce a concrete change brief: problem, desired behavior, non-goals, affected components, acceptance examples, preservation risks, tests and deployment impact. Clearly label proposals versus implemented features. Bring that brief to Codex for source changes and validation. After implementation, update this handoff with the commit, tests and remaining issues. Never upload `.env`, API keys, passwords or confidential customer reports as planning context. Source-repository normalization is included in this cleanup; the next planning brief should address a specific documented limitation, without assuming unimplemented features.
