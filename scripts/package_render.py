"""Build a secret-free Render release upload without changing application code."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'output' / 'render-release'
DEST.mkdir(parents=True, exist_ok=True)
files = [p for folder in ('app', 'settings', 'tests', 'scripts')
         for p in (ROOT / folder).rglob('*')
         if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc']
files += [ROOT / n for n in ('Dockerfile', 'requirements.txt', 'requirements-dev.txt',
                            'pyproject.toml', 'README.md', 'DEPLOYMENT.md')]
manifest = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
with ZipFile(DEST / 'source.zip', 'w', ZIP_DEFLATED) as archive:
    for p in files:
        archive.write(p, p.relative_to(ROOT))
    archive.writestr('release-manifest.json', json.dumps(manifest, indent=2))
# Unpack only during the image build; run the original Dockerfile's exact steps.
original = (ROOT / 'Dockerfile').read_text()
prefix = ('FROM python:3.12-slim AS source\nWORKDIR /release\nCOPY source.zip .\n'
          'RUN python -m zipfile -e source.zip /unpacked\n')
body = original.replace('COPY requirements.txt .', 'COPY --from=source /unpacked/requirements.txt .')
body = body.replace('COPY app ./app', 'COPY --from=source /unpacked/app ./app')
body = body.replace('COPY settings ./settings', 'COPY --from=source /unpacked/settings ./settings')
(DEST / 'Dockerfile').write_text(prefix + body)
(DEST / 'render.yaml').write_text((ROOT / 'render.yaml').read_text())
(DEST / 'README.md').write_text('# AI Language Rewrite 0.3.0\n\nPrivate Render release. '
    'source.zip contains the complete tested application source, writing prompt, tests, '
    'and deployment instructions. The Docker build unpacks it and uses the existing engine. '
    'No API keys or customer documents are included.\n\nRegenerate from the local project '
    'with `python scripts/package_render.py`, then replace these release files.\n')
(DEST / 'release-manifest.json').write_text(json.dumps(manifest, indent=2))
print(DEST)
