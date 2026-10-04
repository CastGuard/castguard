"""설정 로더 (JSON, 추가 패키지 없음)."""
import json
from pathlib import Path

from . import paths


def load_config(path: Path | str = paths.CONFIG) -> dict:
    path = Path(path)
    if not path.is_absolute():
        path = paths.ROOT / path
    return json.loads(path.read_text(encoding="utf-8"))
