from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv('/etc/secrets/.env')  # Optional mounted hosting secret file.
load_dotenv(ROOT / '.env')
DATA_ROOT = Path(os.getenv('DATA_DIR', str(ROOT)))


@dataclass(frozen=True)
class Settings:
    root: Path = ROOT
    prompt_path: Path = ROOT / 'settings' / 'humanizer-prompt.md'
    upload_dir: Path = DATA_ROOT / 'uploads'
    output_dir: Path = DATA_ROOT / 'output'
    model: str = os.getenv('OPENAI_MODEL', 'gpt-5.6-luna')
    max_upload_mb: int = int(os.getenv('MAX_UPLOAD_MB', '50'))
    min_font_scale: float = float(os.getenv('MIN_FONT_SCALE', '0.85'))
    hosted: bool = os.getenv('APP_HOSTED', 'false').lower() == 'true'
    username: str = os.getenv('APP_USERNAME', '')
    password: str = os.getenv('APP_PASSWORD', '')
    retention_hours: int = int(os.getenv('FILE_RETENTION_HOURS', '24' if os.getenv('APP_HOSTED', 'false').lower() == 'true' else '0'))
    allowed_models: tuple[str, ...] = tuple(x.strip() for x in os.getenv('ALLOWED_MODELS', 'gpt-5.6-luna,gpt-5.6-terra,gpt-5.6-sol,gpt-6-astra').split(',') if x.strip())

    def ensure_directories(self) -> None:
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
