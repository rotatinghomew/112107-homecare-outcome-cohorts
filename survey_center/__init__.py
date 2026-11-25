"""居家服务问卷换版的可复核分析与签发流程。

只使用 Python 标准库。所有日期均按本地日历日期比较；资料可见性以
``registered_at`` 为准，统计轮次以回收期限和答卷所属月份为准。
"""

from .io import Dataset, load_dataset
from .classification import classify_reply, classify_response
from .analysis import (
    primary_observations,
    cell_indicator_table,
    indicator_strata_table,
    assigned_arm_table,
    pair_evidence_table,
    comparability_table,
    trend_table,
    region_scope_table,
    pair_records,
    permission_state,
)
from .operations import (
    reconcile_round,
    station_capacity_table,
    station_group_decisions,
)
from .archive import ArchiveGateway

__all__ = [
    "Dataset",
    "load_dataset",
    "ArchiveGateway",
    "classify_reply",
    "classify_response",
    "primary_observations",
    "cell_indicator_table",
    "indicator_strata_table",
    "assigned_arm_table",
    "pair_evidence_table",
    "comparability_table",
    "trend_table",
    "region_scope_table",
    "pair_records",
    "permission_state",
    "reconcile_round",
    "station_capacity_table",
    "station_group_decisions",
]
