from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .io import Dataset


@dataclass
class ArchiveGateway:
    """Read-only entry point for already published annual-report excerpts.

    It intentionally has no method that returns paired individual questionnaires.
    Analysts need :func:`survey_center.pair_records` with a current permission
    check; the archive reader must never join that data to old report entries.
    """

    ds: Dataset

    def list_reports(self) -> list[dict[str, str]]:
        return [dict(row) for row in self.ds.table("archive_reports.csv")]

    def get_report(self, report_id: str) -> dict[str, str]:
        for row in self.ds.table("archive_reports.csv"):
            if row["report"] == report_id:
                return dict(row)
        raise KeyError(f"找不到旧公报：{report_id}")

    def paired_household_responses(self, *_args: Any, **_kwargs: Any) -> None:
        raise PermissionError("旧年报入口只能查看已发布汇总，不能调阅或下钻成对个户答卷。")
