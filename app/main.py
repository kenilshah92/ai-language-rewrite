from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
import json
import mimetypes
from pathlib import Path
import secrets
import threading
import time
import uuid
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from openai import OpenAIError
import pymupdf as fitz

from app.config import settings
from app.humanizer import Humanizer, HumanizerError
from app.pdf_pipeline import process_pdf
from app.pdf_rewriter import extract_text_blocks, report_to_dict, rewrite_pdf
from app.document_rewriter import ContentBlock, extract_docx, extract_txt, rewrite_docx, rewrite_txt

security = HTTPBasic(auto_error=False)
jobs: dict[str, dict] = {}
job_lock = threading.Lock()
executor = ThreadPoolExecutor(max_workers=2)
FORMATS = {'.pdf', '.docx', '.txt'}


def _cleanup() -> None:
    if settings.retention_hours <= 0:
        return
    cutoff = time.time() - settings.retention_hours * 3600
    with job_lock:
        active = {key for key, job in jobs.items() if job['status'] in ('queued', 'processing', 'uploading')}
        for key in list(jobs):
            if key not in active and jobs[key]['created_at'] < cutoff:
                jobs.pop(key)
    for directory in (settings.upload_dir, settings.output_dir):
        for path in directory.iterdir():
            if path.is_file() and path.name.split('-')[0] not in active and path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)


async def _cleanup_loop():
    while True:
        await asyncio.sleep(300)
        await asyncio.to_thread(_cleanup)


@asynccontextmanager
async def lifespan(app):
    if settings.hosted and (not settings.username or len(settings.password) < 16):
        raise RuntimeError('Hosted mode requires APP_USERNAME and an APP_PASSWORD of at least 16 characters in the secret .env file.')
    if settings.hosted and settings.retention_hours <= 0:
        raise RuntimeError('Hosted mode requires a positive FILE_RETENTION_HOURS value.')
    settings.ensure_directories()
    _cleanup()
    task = asyncio.create_task(_cleanup_loop())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(title='AI Language Rewrite', version='0.3.0', lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
settings.ensure_directories()


def authenticate(credentials: HTTPBasicCredentials | None = Depends(security)):
    if not settings.hosted and not settings.password:
        return
    valid = credentials is not None and secrets.compare_digest(credentials.username.encode(), settings.username.encode()) and secrets.compare_digest(credentials.password.encode(), settings.password.encode())
    if not valid:
        raise HTTPException(401, 'Sign in to use this private app.', headers={'WWW-Authenticate': 'Basic realm="AI Language Rewrite"'})


@app.middleware('http')
async def private_responses(request, call_next):
    origin = request.headers.get('origin')
    if request.method == 'POST' and origin and urlsplit(origin).netloc != request.headers.get('host'):
        from fastapi.responses import JSONResponse
        return JSONResponse({'detail': 'Cross-site uploads are not allowed.'}, status_code=403)
    response = await call_next(request)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    return response


@app.get('/', response_class=HTMLResponse, dependencies=[Depends(authenticate)])
def home():
    return HTMLResponse((settings.root / 'app/static/index.html').read_text(encoding='utf-8'))


@app.get('/api/config', dependencies=[Depends(authenticate)])
def configuration():
    return {'model': settings.model, 'models': list(dict.fromkeys((settings.model, *settings.allowed_models))), 'max_upload_mb': settings.max_upload_mb, 'hosted': settings.hosted, 'retention_hours': settings.retention_hours}


def _process(job_id: str, source: Path, output: Path, report_path: Path, model: str):
    with job_lock:
        jobs[job_id]['status'] = 'processing'
    try:
        humanizer = Humanizer(settings.prompt_path, model)
        if source.suffix == '.pdf':
            report = process_pdf(source, output, humanizer, settings.min_font_scale)
        else:
            blocks = extract_docx(source) if source.suffix == '.docx' else extract_txt(source)
            if not blocks:
                raise ValueError('No supported editable text was found.')
            replacements = humanizer.rewrite(blocks)
            results = rewrite_docx(source, output, replacements) if source.suffix == '.docx' else rewrite_txt(source, output, replacements)
            report = report_to_dict(results)
            report.update({'prompt_sha256': humanizer.prompt_sha256, 'prompt_snapshot': humanizer.prompt_text})
            for row in report['blocks']:
                row['initial_proposed'] = replacements.get(row['block_id'], row['original'])
        report.update({'model': model, 'format': source.suffix[1:]})
        if source.suffix == '.docx':
            report['layout_note'] = 'Font/style definitions and package assets are preserved. Word may repaginate after text changes; review the document in Word. Complex content is kept original and reported.'
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
        with job_lock:
            jobs[job_id].update(status='complete', filename=output.name, download_url=f'/api/download/{output.name}', report_url=f'/api/download/{report_path.name}', summary=report['summary'], layout_note=report.get('layout_note', ''))
    except Exception as exc:
        # Do not expose SDK responses, credentials, or filesystem details.
        if isinstance(exc, OpenAIError):
            message = 'OpenAI request failed. Check the API key, selected model access, account balance, and connection, then retry.'
        elif isinstance(exc, (ValueError, HumanizerError, UnicodeError)):
            message = str(exc)[:400]
        else:
            message = 'The file could not be processed safely. Check that it is a valid, unprotected supported document.'
        output.unlink(missing_ok=True)
        report_path.unlink(missing_ok=True)
        with job_lock:
            jobs[job_id].update(status='failed', error=message)


@app.post('/api/rewrite', status_code=202, dependencies=[Depends(authenticate)])
async def rewrite(file: UploadFile = File(...), model: str = Form('')):
    suffix = Path(file.filename or '').suffix.lower()
    if suffix not in FORMATS:
        raise HTTPException(400, 'Upload a PDF, DOCX, or UTF-8 TXT file. Legacy .doc, scanned PDFs, and other formats are not supported.')
    selected = model or settings.model
    if selected not in (settings.model, *settings.allowed_models):
        raise HTTPException(400, 'Choose a configured model.')
    job_id = uuid.uuid4().hex
    with job_lock:
        if sum(j['status'] in ('queued', 'processing', 'uploading') for j in jobs.values()) >= 8:
            raise HTTPException(429, 'The app is busy. Please try again after a current rewrite finishes.')
        jobs[job_id] = {'job_id': job_id, 'status': 'uploading', 'created_at': time.time(), 'model': selected}
    stem = _safe_stem(Path(file.filename).stem)
    source = settings.upload_dir / f'{job_id}-{stem}{suffix}'
    output = settings.output_dir / f'{job_id}-{stem}-rewritten{suffix}'
    report = settings.output_dir / f'{job_id}-{stem}-report.json'
    try:
        size = 0
        with source.open('wb') as stream:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > settings.max_upload_mb * 1024 * 1024:
                    raise HTTPException(413, f'File exceeds {settings.max_upload_mb} MB.')
                stream.write(chunk)
        if not size:
            raise HTTPException(400, 'The file is empty.')
        with job_lock:
            jobs[job_id]['status'] = 'queued'
        executor.submit(_process, job_id, source, output, report, selected)
    except BaseException:
        source.unlink(missing_ok=True)
        with job_lock:
            jobs.pop(job_id, None)
        raise
    finally:
        await file.close()
    return {'job_id': job_id, 'status': 'queued', 'status_url': f'/api/jobs/{job_id}'}


@app.post('/api/rewrite-text', dependencies=[Depends(authenticate)])
async def rewrite_text(text: str = Form(''), model: str = Form('')):
    """Rewrite free-form text without creating a document artifact."""
    text = text.strip()
    if not text:
        raise HTTPException(400, 'Enter text to rewrite.')
    selected = model or settings.model
    if selected not in (settings.model, *settings.allowed_models):
        raise HTTPException(400, 'Choose a configured model.')
    block = ContentBlock('free-text', text)
    try:
        rewritten = await asyncio.to_thread(
            lambda: Humanizer(settings.prompt_path, selected).rewrite([block])[block.id]
        )
    except OpenAIError:
        raise HTTPException(502, 'OpenAI request failed. Check model access and connection, then retry.')
    except HumanizerError as exc:
        raise HTTPException(502, str(exc))
    return {'original': text, 'rewritten': rewritten, 'model': selected}


@app.get('/api/jobs/{job_id}', dependencies=[Depends(authenticate)])
def job_status(job_id: str):
    with job_lock:
        if job_id not in jobs:
            raise HTTPException(404, 'Job not found or expired. A server restart also clears pending job status.')
        return dict(jobs[job_id])


@app.get('/api/download/{filename}', dependencies=[Depends(authenticate)])
def download(filename: str):
    if filename != Path(filename).name:
        raise HTTPException(404, 'File not found.')
    path = settings.output_dir / filename
    if not path.is_file():
        raise HTTPException(404, 'File not found or expired.')
    media_type = mimetypes.guess_type(filename)[0] or 'application/octet-stream'
    return FileResponse(path, media_type=media_type, filename=filename)


@app.get('/api/health')
def health():
    return {'status': 'ok'}


def _safe_stem(value: str) -> str:
    cleaned = ''.join(char if char.isalnum() or char in '-_' else '-' for char in value)
    return cleaned.strip('-')[:80] or 'document'
