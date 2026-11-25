from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA = ROOT / "data"


def parse_date(value: str | None) -> date | None:
    """Parse an ISO calendar date; blank values mean unknown/not applicable."""
    if value is None or value == "":
        return None
    return date.fromisoformat(value)


def as_int(value: str | None, default: int = 0) -> int:
    if value is None or value == "":
        return default
    return int(value)


def as_float(value: str | None, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    return float(value)


@dataclass
class Dataset:
    root: Path
    tables: dict[str, list[dict[str, str]]]
    contract: dict[str, Any]

    def table(self, name: str) -> list[dict[str, str]]:
        if name not in self.tables:
            raise KeyError(f"缺少数据表：{name}")
        return self.tables[name]

    def first(self, name: str, **criteria: str) -> dict[str, str] | None:
        for row in self.table(name):
            if all(row.get(k) == v for k, v in criteria.items()):
                return row
        return None

    def find(self, name: str, **criteria: str) -> list[dict[str, str]]:
        return [
            row
            for row in self.table(name)
            if all(row.get(k) == v for k, v in criteria.items())
        ]


def load_dataset(root: str | Path = DEFAULT_DATA) -> Dataset:
    """Load every CSV listed in data-contract.json.

    ``root`` may be either the repository root (containing ``data/``) or the
    data directory itself.  The loader intentionally keeps raw string values.
    Domain functions parse dates and numerics so audit outputs can still show
    the original CSV text.
    """
    root = Path(root)
    if (root / "data-contract.json").exists() and (root / "data").is_dir():
        project_root = root
        data_root = root / "data"
    else:
        data_root = root
        project_root = root.parent if (root.parent / "data-contract.json").exists() else root
    contract_path = project_root / "data-contract.json"
    if not contract_path.exists():
        contract_path = data_root / "data-contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))

    tables: dict[str, list[dict[str, str]]] = {}
    for name in contract["files"]:
        path = data_root / name
        with path.open(encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream, strict=True)
            tables[name] = list(reader)
    return Dataset(root=data_root, tables=tables, contract=contract)


def write_csv(path: str | Path, rows: Iterable[dict[str, Any]], fields: list[str] | None = None) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    materialized = list(rows)
    if fields is None:
        fields = list(materialized[0].keys()) if materialized else []
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in materialized:
            writer.writerow({k: _csv_value(row.get(k, "")) for k in fields})
    return path


def _csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, float):
        # Avoid scientific notation and keep audit tables compact.
        return f"{value:.6f}".rstrip("0").rstrip(".")
    if isinstance(value, bool):
        return "是" if value else "否"
    return value
