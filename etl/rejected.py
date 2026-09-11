"""Registro de alimentos descartados (documento 2, sección 11.2)."""

import json
from dataclasses import dataclass
from pathlib import Path

REJECTED_DIR = Path(__file__).parent / "rejected"


@dataclass
class Rejection:
    source: str
    source_id: str | None
    name: str | None
    reason: str


def log_rejections(source: str, rejections: list[Rejection]) -> Path:
    REJECTED_DIR.mkdir(parents=True, exist_ok=True)
    out_path = REJECTED_DIR / f"{source}.jsonl"
    with out_path.open("w", encoding="utf-8") as f:
        for r in rejections:
            f.write(
                json.dumps(
                    {
                        "source_id": r.source_id,
                        "name": r.name,
                        "reason": r.reason,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    return out_path
