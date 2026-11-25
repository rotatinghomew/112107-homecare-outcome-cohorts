from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .io import Dataset


class IssuanceError(ValueError):
    """Raised when an arrangement would promise unsupported continuity."""


@dataclass(frozen=True)
class Arrangement:
    station: str
    group: str
    mode: str
    original_interviews: int
    new_interviews: int
    new_self_forms: int
    total_forms: int
    trend_continuity_promised: bool
    basis: str
    warning: str


def draft_arrangement(
    ds: Dataset,
    station: str,
    group: str,
    mode: str = "auto",
) -> Arrangement:
    """Create a guarded next-round arrangement draft.

    Modes:
    - ``auto``: use the policy/capacity recommendation;
    - ``full_new``: retire the original for the whole group (requires evidence);
    - ``original_coverable`` / ``dual_track``: retain same-caliber interviews up to capacity;
    - ``restart_new``: explicitly break the trend and start a new series.
    """
    from .operations import station_group_decisions

    decisions = {(r["station"], r["group"]): r for r in station_group_decisions(ds)}
    if (station, group) not in decisions:
        raise KeyError(f"找不到站组：{station}·{group}")
    row = decisions[(station, group)]

    if mode == "full_new":
        if not row["full_switch_allowed"]:
            raise IssuanceError(
                f"不能整组退原版：{row['policy_reasons']}；"
                f"渠道就绪={row['full_group_channel_ready']}。"
                "可改为 original_coverable、dual_track 或 restart_new。"
            )
        return Arrangement(
            station, group, mode, 0,
            int(row["recommended_new_interviews"]),
            int(row["recommended_new_self_forms"]),
            40,
            True,
            row["policy_reasons"],
            "自填户与无自填条件但接受新版访谈的户合计覆盖全组。",
        )

    if mode in {"original_coverable", "dual_track"}:
        original = int(row["recommended_original_interviews"])
        new_interview = int(row["recommended_new_interviews"])
        new_self = int(row["recommended_new_self_forms"])
        promises = False
        warning = (
            "这不是全组切换；年报必须列示未覆盖户及权重。"
            if not row["current_comparable"]
            else "双轨仅用于额外复核，不能把部分换版表述为全组已切换。"
        )
        return Arrangement(
            station, group, mode, original, new_interview, new_self,
            original + new_interview + new_self, promises, row["policy_reasons"], warning
        )

    if mode == "restart_new":
        return Arrangement(
            station, group, mode, 0,
            int(row["restart_new_series_new_interviews"]),
            int(row["restart_new_series_self_forms"]),
            40,
            False,
            row["policy_reasons"],
            "从本期重开序列；旧趋势不得继续承诺，失去连续性的户和范围须在年报中单列。",
        )

    if mode == "auto":
        auto_mode = "full_new" if row["full_switch_allowed"] else "original_coverable"
        arrangement = draft_arrangement(ds, station, group, auto_mode)
        return Arrangement(**{**asdict(arrangement), "mode": "auto->" + auto_mode})

    raise ValueError(f"未知签发模式：{mode}")


def write_arrangement(arrangement: Arrangement, outdir: str | Path) -> Path:
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    safe_station = arrangement.station
    path = outdir / f"{safe_station}_{arrangement.group}_{arrangement.mode.replace('->', '_')}.json"
    if path.exists():
        raise FileExistsError(f"签发安排已存在，不能覆盖：{path}")
    path.write_text(json.dumps(asdict(arrangement), ensure_ascii=False, indent=2), encoding="utf-8")
    return path
