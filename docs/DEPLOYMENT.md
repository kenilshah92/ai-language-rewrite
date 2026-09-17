# Deployment

## Current deployment and source layout

The app is running at https://ai-language-rewrite.onrender.com on Render's free Docker web-service tier in Singapore. Service ID: `srv-dahftjuk1f9s73flfc10`. The initial successful deployment used private repository https://github.com/kenilshah92/ai-language-rewrite, branch `main`, commit `7e5179bbde30680006010f61e71020a738020cd4`. Render startup/health logs were verified during initial deployment; the owner subsequently confirmed the app works. These are recorded observations, not continuous monitoring.

## Source-based deployment

The repository now stores ordinary source files under app/, settings/, tests/, scripts/ and docs/. The root Dockerfile copies application source directly. The source.zip wrapper and release manifest are removed in this migration; the original release remains recoverable from Git history. Application and prompt bytes were compared with the original archive and are unchanged.

Local main tracks origin/main. This cleanup is one commit on top of 7e5179bbde30680006010f61e71020a738020cd4, without rewriting history or using a long-lived development branch. Pushes to main trigger Render auto-deploy and may interrupt active jobs. Check deployment status after pushing; commit creation alone does not prove deployment success.

render.yaml now selects the free plan to match the owner's chosen live configuration. scripts/package_render.py is retained only as a legacy packaging utility; do not use its archive layout for normal releases. Commit source changes directly. Its legacy archive does not include docs/ or AGENTS.md.

## Runtime and commands

Use Python 3.11+; the root image uses `python:3.12-slim`. The inspected local virtual environment is Python 3.14.6. No Node build, office suite, OCR runtime, database or persistent queue is required. Docker is not currently available on the inspected Mac's PATH; the initial image build succeeded on Render.

From the source root:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
# Copy only when .env does not already exist:
cp .env.example .env
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Set your key privately in `.env`. For tests without real API requests, a non-secret dummy key can satisfy SDK construction: `OPENAI_API_KEY=test-only python -m pytest -q`.

```sh
python -m pytest -q
PYTHONPATH=. python scripts/smoke_test.py
docker build -t ai-language-rewrite .
docker run --rm -p 127.0.0.1:8000:8000 --mount type=bind,src=/absolute/path/to/hosted.env,dst=/etc/secrets/.env,readonly ai-language-rewrite
```

The Dockerfile creates non-root UID 10001 and writable `/data`, uses one Uvicorn worker, binds `0.0.0.0`, and honors `PORT` (fallback 8000). Render provides HTTPS and its runtime port. Health path is `/api/health`. Health confirms process availability, not successful OpenAI requests or rendering correctness.

## Configuration

Keep keys/passwords out of Git, chat handoffs and logs. `.env.example` is a placeholder template. Use a Render secret file named `.env`, mounted at `/etc/secrets/.env`; keep one `KEY=value` setting per line. The OpenAI key is not a GitHub access token.

| Variable | Default / behavior |
| --- | --- |
| `OPENAI_API_KEY` | No application default; read by the SDK when a job creates a client |
| `OPENAI_MODEL` | `gpt-5.6-luna`; model access must exist on the API account |
| `ALLOWED_MODELS` | `gpt-5.6-luna,gpt-5.6-terra,gpt-5.6-sol,gpt-6-astra`; default model is also allowed even if omitted here |
| `APP_HOSTED` | `false` locally; Docker sets `true`; only case-insensitive `true` enables hosted mode |
| `APP_USERNAME` | Empty default; required in hosted mode |
| `APP_PASSWORD` | Empty default; hosted startup requires at least 16 characters |
| `FILE_RETENTION_HOURS` | 0 locally, 24 when APP_HOSTED is true; hosted startup rejects 0 or negative values |
| `MAX_UPLOAD_MB` | 50; implemented as MiB (1024 × 1024 bytes) |
| `MIN_FONT_SCALE` | 0.85; PDF font-size floor relative to source size |
| `DATA_DIR` | Project root locally; `/data` in Docker |
| `PORT` | Docker command defaults to 8000 if absent; supplied by host |
| `PYTHONDONTWRITEBYTECODE`, `PYTHONUNBUFFERED` | Docker sets both to 1 |

Already-set process variables win over secret files. Secret-file values win over local `.env`. The app does not clamp all numeric settings to sensible ranges; retain documented defaults unless investigating a specific change. The prompt path is fixed to `settings/humanizer-prompt.md`. There is no runtime setting for worker count or queue capacity.

## Storage, security and operational limits

Keep `/data` writable by UID 10001. The app stores uploaded originals, output files and full-text JSON reports there, not in GitHub. No external storage or app telemetry is configured. Reports include prompt text; protect them like source documents. OpenAI receives extracted text/context, not original files. Provider-side storage policy is not configured in code.

Free instances sleep after inactivity; the Render UI warns wake-up may take 50 seconds or more. Free service configuration observed during setup: 0.1 CPU, 512 MB RAM. PDF processing, large ZIP expansion and simultaneous uploads can exceed these resources; 50 MiB acceptance is not a capacity test. API calls remain chargeable even with free hosting.

Use one instance and one process. In-memory jobs are not shared between workers and are lost on restart. There is no durable retry/recovery. Files expire via a five-minute cleanup loop and ephemeral disks disappear on replacement/redeploy. Download promptly. A sleeping instance cannot run cleanup until awake. Active jobs are exempt, so 24 hours is not an exact deletion SLA. The shared login is suitable only for mutually trusted users; it does not isolate their files.

HTTPS termination is required for Basic authentication. No external identity provider, individual invitations, usage quotas or abuse-rate limiter is included. Eight active jobs is concurrency admission control, not a complete resource or billing quota. Observe actual usage before considering paid compute, persistent queue/storage or per-user accounts.

## Release checklist

1. Review actual source and prompt changes; do not include `.env`, customer files, output, tmp or the local virtual environment.
2. Run tests and the PDF smoke check. For rendering changes, compare representative source/output pages as well.
3. Build on a Docker-capable machine or verify Render's build logs. Broad dependency ranges mean a rebuild can resolve newer versions.
4. Preserve the configured free plan, secret file, region, health path and one-worker setup.
5. Confirm startup and health; unauthenticated app/download/config requests should return 401.
6. Test a small PDF, DOCX and TXT using the deployed app and check reports/downloads. Local unit tests are not a substitute for this live acceptance check.
7. Record the deployed commit and remaining limitations in CURRENT_STATE.md. Do not claim a live rewrite passed unless observed.
