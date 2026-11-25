from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .analysis import (
    assigned_arm_table,
    cell_indicator_table,
    comparability_table,
    indicator_strata_table,
    pair_evidence_table,
    region_scope_table,
    trend_table,
)
from .io import Dataset, write_csv
from .operations import reconcile_round, station_capacity_table, station_group_decisions


def pct(value: Any, digits: int = 1) -> str:
    if value in (None, ""):
        return "证据不足"
    return f"{float(value) * 100:.{digits}f}%"


def pp(value: Any, digits: int = 1) -> str:
    if value in (None, ""):
        return "不可比/不足"
    sign = "+" if float(value) > 0 else ""
    return f"{sign}{float(value) * 100:.{digits}f}pp"


def yes_no(value: Any) -> str:
    if value is True:
        return "是"
    if value is False:
        return "否"
    return str(value)


def markdown_table(rows: list[dict[str, Any]], columns: list[tuple[str, str] | tuple[str, str, str]]) -> str:
    header = "| " + " | ".join(column[1] for column in columns) + " |"
    sep = "| " + " | ".join("---" for _ in columns) + " |"
    lines = [header, sep]
    for row in rows:
        values = []
        for column in columns:
            key, label = column[0], column[1]
            kind = column[2] if len(column) > 2 else "text"
            value = row.get(key, "")
            if kind == "pct":
                text = pct(value)
            elif kind == "pp":
                text = pp(value)
            elif kind == "bool":
                text = yes_no(value)
            else:
                text = "" if value is None else str(value)
            text = text.replace("|", "/").replace("\n", "；")
            values.append(text)
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def build_outputs(ds: Dataset, outdir: str | Path) -> dict[str, Path]:
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    indicators = cell_indicator_table(ds)
    strata = indicator_strata_table(ds)
    arms = assigned_arm_table(ds)
    pairs = pair_evidence_table(ds)
    comps = comparability_table(ds)
    trends = trend_table(ds)
    regions = region_scope_table(ds)
    decisions = station_group_decisions(ds)
    capacity = station_capacity_table(ds)
    current = reconcile_round(ds)
    initial = reconcile_round(ds, as_of="2026-08-01")

    outputs = {
        "indicator_cells.csv": write_csv(outdir / "indicator_cells.csv", indicators),
        "indicator_strata.csv": write_csv(outdir / "indicator_strata.csv", strata),
        "assigned_arm_evidence.csv": write_csv(outdir / "assigned_arm_evidence.csv", arms),
        "pair_evidence.csv": write_csv(outdir / "pair_evidence.csv", pairs),
        "comparability.csv": write_csv(outdir / "comparability.csv", comps),
        "trends.csv": write_csv(outdir / "trends.csv", trends),
        "region_scopes.csv": write_csv(outdir / "region_scopes.csv", regions),
        "station_decisions.csv": write_csv(outdir / "station_decisions.csv", decisions),
        "capacity.csv": write_csv(outdir / "capacity.csv", capacity),
        "july_reconciliation_current_details.csv": write_csv(
            outdir / "july_reconciliation_current_details.csv", current.details
        ),
        "july_notice_reconciliation_current.csv": write_csv(
            outdir / "july_notice_reconciliation_current.csv", current.notices
        ),
        "july_reconciliation_asof_2026-08-01_details.csv": write_csv(
            outdir / "july_reconciliation_asof_2026-08-01_details.csv", initial.details
        ),
        "july_notice_reconciliation_asof_2026-08-01.csv": write_csv(
            outdir / "july_notice_reconciliation_asof_2026-08-01.csv", initial.notices
        ),
        "archive_reports_view.csv": write_csv(
            outdir / "archive_reports_view.csv",
            ds.table("archive_reports.csv"),
            fields=list(ds.contract["files"]["archive_reports.csv"]["columns"]),
        ),
    }
    report_path = outdir / "analysis_and_dispatch.md"
    report_path.write_text(render_report(ds, comps, trends, regions, decisions, capacity, current, initial), encoding="utf-8")
    outputs["analysis_and_dispatch.md"] = report_path
    return outputs


def render_report(ds, comps, trends, regions, decisions, capacity, current, initial) -> str:
    qualified = [r for r in comps if r["comparable"]]
    suspended = [r for r in decisions if r["suspend_unissued_switch_for_review"]]
    lines: list[str] = []
    lines.append("# 问卷换版、趋势衔接与七月收发对账\n")
    lines.append(
        "本报告由 `python3 -m survey_center build` 从 CSV 重新生成。当前重分析使用全部已登记记录；"
        "首次发布快照另存于 `publications/`，后续登记不回写快照。\n"
    )

    lines.append("## 一、口径与隐私红线\n")
    lines.append(
        "- 指标为过去四周因**联络方式或可达时段**没能提出求助的户比例；分母只含可判定该目标状态的有效观测。\n"
        "- 整份未回、明确拒答、已答无困难、新版称有障碍但原因空白/仅填“其他主要原因”分别计数；后两类不判为无联络/时段障碍。\n"
        "- 每户在同一站点同一统计期只取**实际首先出示版本**的一份主观测；首份缺失、拒答或口径未明时，不用第二份填补。\n"
        "- 成对记录仅在当前存在有效关联许可时用于问法/次序分析；H003、H083 的关联已撤回，当前成对证据不含该两对，但其保留单份的首份答卷仍进入主指标。\n"
        "- `archive_reports_view.csv` 和旧年报入口只展示已发布汇总值，不提供成对个户答卷或下钻链接。\n"
    )

    lines.append("## 二、站组指标与政策判定（2026-06）\n")
    lines.append(
        markdown_table(
            comps,
            [
                ("station", "站点"),
                ("group", "服务组"),
                ("households", "名册户"),
                ("known_target_households", "有效口径n"),
                ("barrier_households", "障碍户"),
                ("barrier_rate", "障碍比例", "pct"),
                ("refused_households", "拒答"),
                ("missing_households", "整份未回"),
                ("unresolved_answer_households", "答案未明"),
                ("unresolved_rate", "未明/失访率", "pct"),
                ("lower_bound_all_assigned", "下限/40", "pct"),
                ("upper_bound_all_assigned", "上限/40", "pct"),
                ("pair_analyzable_pairs", "可用配对"),
                ("pair_version_bias_abs", "换版偏差", "pct"),
                ("order_effect_policy", "次序效应(保守)", "pct"),
                ("comparable", "判定", "bool"),
            ],
        )
    )
    lines.append("\n\n判定说明：\n")
    for row in comps:
        lines.append(f"- **{row['station']}·{row['group']}**：{row['reasons']}。")
    lines.append(
        "表中下限为已证实障碍户/40，上限假设所有拒答、失访和未明户均为障碍；"
        "若区间跨越政策或趋势阈值，结论应表述为受失访/拒答影响，而不能只报告有效样本率。"
    )
    lines.append("")

    strata = indicator_strata_table(ds)
    arms = assigned_arm_table(ds)
    lines.append("### 2.1 两用试填组、两用常规组与只能访谈群体\n")
    lines.append(
        markdown_table(
            strata,
            [
                ("station", "站点"),
                ("group", "服务组"),
                ("stratum", "分层"),
                ("households", "户数"),
                ("known_target_households", "有效n"),
                ("barrier_households", "障碍户"),
                ("barrier_rate", "障碍比例", "pct"),
                ("refused_households", "拒答"),
                ("missing_households", "未回"),
                ("unresolved_answer_households", "未明"),
            ],
        )
    )
    lines.append("\n")
    lines.append("### 2.2 原随机分配组的可见结果（保留临时换序/失访痕迹）\n")
    lines.append(
        markdown_table(
            arms,
            [
                ("station", "站点"),
                ("group", "服务组"),
                ("assigned_first", "原分配首版"),
                ("assigned_households", "分配户"),
                ("adaptation_switches", "适配转序"),
                ("actual_first_original", "实际原版先"),
                ("actual_first_new", "实际新版先"),
                ("known_target_households", "有效n"),
                ("barrier_households", "障碍户"),
                ("barrier_rate", "障碍比例", "pct"),
                ("refused_households", "拒答"),
                ("missing_households", "未回"),
            ],
        )
    )
    lines.append("\n临时换序均为“原分配新版、实际原版先”的适配转序，不能把实际次序组当作随机组；配对表同时列示分配次序和实际次序效应。\n")
    total_random = sum(r["pair_random_assigned_households"] for r in comps)
    total_pairs = sum(r["pair_analyzable_pairs"] for r in comps)
    lines.append(
        f"**差异来源读法：**配对口径差看 `version_bias_new_minus_old`（同一户两版的边际率差）；"
        "学习/先后影响看两种次序下 new−old 差值的差；受访人构成与失访看上方原分配臂、"
        f"渠道分层及 `second_copy_missing`。{total_random} 个随机试填户当前只有 {total_pairs} 个经授权且两版口径可判的配对，"
        f"并有 {sum(a['adaptation_switches'] for a in arms)} 户适配转序；因此配对结果只用于校准，"
        "不能反过来替代主指标或假设失访户与完成户相同。\n"
    )

    lines.append("## 三、趋势能否连接\n")
    lines.append(
        markdown_table(
            trends,
            [
                ("station", "站点"),
                ("group", "服务组"),
                ("jan_raw_barrier", "一月重算障碍户"),
                ("jan_raw_households", "一月有效n"),
                ("jan_raw_rate", "一月重算率", "pct"),
                ("june_barrier", "六月障碍户"),
                ("june_households", "六月有效n"),
                ("june_rate", "六月率", "pct"),
                ("raw_change_pp", "重算变化", "pp"),
                ("archive_jan_report", "旧公报"),
                ("archive_jan_rate", "公报一月率", "pct"),
                ("archive_change_pp", "较公报", "pp"),
                ("can_connect_published_archive", "可连公报", "bool"),
                ("trend_statement", "结论"),
            ],
        )
    )
    p03 = ds.first("archive_reports.csv", report="P03")
    p03_sentence = ""
    if p03:
        p03_rate = int(p03["barrier_households"]) / int(p03["households"])
        p03_sentence = (
            f" P03 已按“{p03['scope']}”公布 {p03['barrier_households']}/{p03['households']}"
            f"（{p03_rate * 100:.1f}%）；该值保持原样，当前重算只作复核，不回写公报。"
            "H083 关联撤回后，新桥·持续照护仍满足配对门槛，因此没有新的证据要求停止该趋势口径，"
            "但对外仍应引用 P03 原值并说明当前范围/权重。"
        )
    lines.append(
        "\n\n旧公报 P01–P03 按档案原值保留；它们不是用当前记录重算的结果，系统只读取、不回写。"
        "可比组为 "
        + "、".join(f"{r['station']}·{r['group']}" for r in qualified)
        + "。这些组的原始名册重算变化均未超过 9pp 换版容许偏差，不能宣称出现了已证实的“求助变方便”；"
        "其余四个组不得把率差直接解释为服务改善或恶化。"
        + p03_sentence
        + "\n"
    )

    lines.append("## 四、全区范围与权重\n")
    lines.append(
        markdown_table(
            regions,
            [
                ("scope", "范围"),
                ("cells", "站组"),
                ("roster_households", "名册户/权重基数"),
                ("district_weight", "全区权重", "pct"),
                ("june_known_households", "六月有效n"),
                ("june_rate", "六月率", "pct"),
                ("jan_raw_rate", "一月重算率", "pct"),
                ("raw_change_pp", "变化", "pp"),
                ("trend_connectable", "可连接", "bool"),
                ("note", "说明"),
            ],
        )
    )
    lines.append(
        "\n\n区级混合值只用于列示。先有站组独立判定，后汇总可比/不可比范围；不能反过来用全区数值推定任何站点或服务组合格。\n"
    )

    lines.append("## 五、主管签发与能力核对\n")
    lines.append(
        markdown_table(
            decisions,
            [
                ("station", "站点"),
                ("group", "服务组"),
                ("notice", "发布单"),
                ("current_comparable", "当前可比", "bool"),
                ("at_cutoff_comparable", "签发日可见证据可比", "bool"),
                ("post_signing_permission_or_order_events", "签发后事件数"),
                ("decision", "安排建议"),
                ("recommended_original_interviews", "建议原版访谈"),
                ("recommended_new_interviews", "建议新版访谈"),
                ("recommended_new_self_forms", "建议新版自填"),
                ("suspend_unissued_switch_for_review", "暂挂未发换版", "bool"),
                ("trend_commitment_review", "趋势承诺复核"),
            ],
        )
    )
    lines.append("\n\n站点能力（含两个服务组协同排程）：\n")
    lines.append(
        markdown_table(
            capacity,
            [
                ("station", "站点"),
                ("capacity_hours", "访谈小时"),
                ("booked_interview_hours", "已占小时"),
                ("remaining_bookable_minutes", "剩余分钟"),
                ("max_original_interviews_stationwide", "全站原版访谈上限"),
                ("equal_split_original_per_group", "两组均分/组"),
                ("self_service_limit", "自填上限"),
                ("self_service_used_so_far", "已用自填"),
                ("coordinated_plan_minutes", "协同方案分钟"),
                ("coordinated_plan_capacity_ok", "协同方案可行", "bool"),
            ],
        )
    )
    if suspended:
        lines.append("\n\n**必须暂挂的未发放换版份额：**")
        for row in suspended:
            lines.append(
                f"- {row['notice']}（{row['station']}·{row['group']}）：{row['unissued_new_forms_to_suspend']} "
                "份尚未发放的新版/换版份额依据已不足，暂挂复核；已约访谈继续占用时段，已发问卷按实际版本回收。"
            )
    lines.append(
        "\n\n北苑两个组均未过政策门槛；若两组都全量保留原版，需要1120分钟，超过480分钟能力。"
        "全站最多安排34份原版访谈，两组均分约17份/组，其余户必须明确列入缩减同口径范围、双轨安排或新序列权重，不能静默移出年报。\n"
    )

    lines.append("## 六、七月收发对账（当前全部已登记记录）\n")
    lines.append(
        markdown_table(
            current.notices,
            [
                ("notice", "发布单"),
                ("station", "站点"),
                ("group", "服务组"),
                ("agreed_total", "承诺份数"),
                ("actual_dispatches", "已约/已发记录"),
                ("unissued_total", "未行动计划份额"),
                ("roster_households", "全组名册户"),
                ("roster_not_covered_by_notice", "发布单未覆盖户"),
                ("valid_indicator_households", "当期有效口径"),
                ("valid_barrier_households", "障碍户"),
                ("no_visible_receipt", "未回/不可见"),
                ("explicit_refusal", "明确拒答"),
                ("caliber_unusable", "口径未明"),
                ("late_processing_only", "逾期仅办理"),
            ],
        )
    )
    lines.append("\n\n逐份回执处置：\n")
    lines.append(
        markdown_table(
            current.details,
            [
                ("receipt", "回执"),
                ("notice", "发布单"),
                ("household", "户"),
                ("actual_form", "实际版本"),
                ("channel", "渠道"),
                ("dispatch_state", "办理状态"),
                ("returned_at", "实际回收"),
                ("receipt_registered_at", "登记日"),
                ("return_timing", "期限"),
                ("disposition_label", "处置"),
                ("included_in_indicator", "入指标", "bool"),
            ],
        )
    )
    lines.append(
        "\n\n要点：J03 是明确拒答；J10（仅“其他”）和 J11（有障碍无原因）已回收但不能判为无联络/时段障碍；"
        "J13 在7月31日按期交回、8月2日才登记，当前回收归 N3/2026-07 原轮次；"
        "J14 于8月1日逾期交回，只进入办理记录，不进入七月指标。\n"
    )

    lines.append("## 七、首次发布快照与后续轮次\n")
    lines.append(
        f"以 `as_of={initial.as_of}` 重放首次发布可见记录时，N3 的 J13/J14 尚未登记，"
        "因此初报只能写当时可见的回收；之后当前表可补计 J13，但不得改写已发布快照。"
        "后续月份继续使用 `reconcile_round(month=..., close_at=..., as_of=...)`："
        "先核对发布单承诺覆盖和渠道，再核对实际发放/约访、回收、拒答、未明与逾期有效回收，"
        "最后决定调整收发方式，还是为读者单开一段新趋势。\n"
    )
    return "\n".join(lines)


def publish_snapshot(ds: Dataset, as_of: str, outdir: str | Path, *, overwrite: bool = False) -> dict[str, Path]:
    """Write an immutable-as-intended publication snapshot.

    The file name includes the knowledge cutoff.  By default an existing
    snapshot is not overwritten, mirroring the rule that late registrations do
    not rewrite the first publication.
    """
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    result = reconcile_round(ds, as_of=as_of)
    stamp = as_of.replace("-", "")
    md_path = outdir / f"{stamp}-period-reconciliation-initial.md"
    json_path = outdir / f"{stamp}-period-reconciliation-initial.json"
    if md_path.exists() and not overwrite:
        raise FileExistsError(f"首次发布快照已存在，不得回写：{md_path}")

    total_valid = sum(n["valid_indicator_households"] for n in result.notices)
    payload = {
        "knowledge_cutoff": as_of,
        "period_close": result.close_at,
        "rule": "Only records registered by knowledge_cutoff are visible; this snapshot must not be rewritten by later registrations.",
        "notice_reconciliation": result.notices,
        "visible_details": result.details,
        "total_valid_indicator_households_visible": total_valid,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        f"# 首次发布对账快照（资料截至 {as_of}）\n",
        "本文件只包含该截至日已登记可见的记录；后续登记不回写本初报。\n",
        markdown_table(
            result.notices,
            [
                ("notice", "发布单"),
                ("station", "站点"),
                ("group", "服务组"),
                ("agreed_total", "承诺份数"),
                ("actual_dispatches", "可见发放/约访"),
                ("valid_indicator_households", "当时可见有效户"),
                ("valid_barrier_households", "障碍户"),
                ("no_visible_receipt", "未见回执"),
                ("explicit_refusal", "拒答"),
                ("caliber_unusable", "口径未明"),
                ("late_processing_only", "逾期"),
            ],
        ),
        "\n\n## 可见逐份记录\n",
        markdown_table(
            result.details,
            [
                ("receipt", "回执"),
                ("notice", "发布单"),
                ("household", "户"),
                ("actual_form", "版本"),
                ("returned_at", "回收日"),
                ("receipt_registered_at", "登记日"),
                ("disposition_label", "处置"),
                ("included_in_indicator", "入指标", "bool"),
            ],
        ),
        "\n",
    ]
    md_path.write_text("\n".join(lines), encoding="utf-8")
    write_csv(outdir / f"{stamp}-notice-reconciliation.csv", result.notices)
    write_csv(outdir / f"{stamp}-details.csv", result.details)
    return {"markdown": md_path, "json": json_path}
