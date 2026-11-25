from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

from .analysis import comparability_table
from .classification import classify_response
from .io import Dataset, as_int, parse_date


@dataclass
class ReconciliationResult:
    as_of: str | None
    close_at: str
    details: list[dict[str, Any]]
    notices: list[dict[str, Any]]


def _roster_index(ds: Dataset, month: str) -> dict[tuple[str, str], dict[str, str]]:
    roster_rows = ds.table("roster.csv")
    months = sorted({r["month"] for r in roster_rows if parse_date(r["month"] + "-01")})
    target = parse_date(month + "-01") or parse_date(month)
    applicable = [m for m in months if parse_date(m + "-01") <= target] if target else months
    roster_month = applicable[-1] if applicable else (months[-1] if months else month)
    # Key by the requested business month so July can transparently use the
    # June roster that README says remains in force.
    return {(month, r["household"]): r for r in ds.find("roster.csv", month=roster_month)}


def reconcile_round(
    ds: Dataset,
    month: str = "2026-07",
    close_at: str = "2026-07-31",
    as_of: str | None = None,
    *,
    dispatch_table: str | None = None,
    receipt_table: str | None = None,
    dispatch_rows: list[dict[str, str]] | None = None,
    receipt_rows: list[dict[str, str]] | None = None,
) -> ReconciliationResult:
    """Reconcile notice commitments, actual sends/appointments and receipts.

    ``as_of`` filters records by ``registered_at``, reproducing what a first
    publication could have seen.  Call with ``as_of=None`` for current recovery;
    on-time returns registered late are then assigned back to the original round.

    Future rounds can pass ``dispatch_rows``/``receipt_rows`` or table names with
    the same columns; the rest of the workflow does not depend on July filenames.
    """
    cutoff = parse_date(as_of) if as_of else None

    def visible(row: dict[str, str]) -> bool:
        if cutoff is None:
            return True
        registered = parse_date(row.get("registered_at"))
        return registered is not None and registered <= cutoff

    notices = ds.table("notices.csv")
    notice_by_id = {n["notice"]: n for n in notices if n.get("month") == month}
    roster = _roster_index(ds, month)

    if dispatch_rows is None:
        if dispatch_table is None:
            dispatch_table = "july_dispatches.csv" if month == "2026-07" else f"{month}_dispatches.csv"
        dispatch_rows = ds.table(dispatch_table)
    if receipt_rows is None:
        if receipt_table is None:
            receipt_table = "july_receipts.csv" if month == "2026-07" else f"{month}_receipts.csv"
        receipt_rows = ds.table(receipt_table)

    dispatches = [d for d in dispatch_rows if visible(d)]
    receipts = [r for r in receipt_rows if visible(r)]
    receipt_by_id = {r["receipt"]: r for r in receipts}
    close_date = parse_date(close_at)

    details: list[dict[str, Any]] = []
    for dispatch in sorted(dispatches, key=lambda d: d["receipt"]):
        notice = notice_by_id.get(dispatch["notice"], {})
        member = roster.get((month, dispatch["household"]), {})
        receipt = receipt_by_id.get(dispatch["receipt"])
        base = {
            "receipt": dispatch["receipt"],
            "notice": dispatch["notice"],
            "station": notice.get("station", member.get("station", "")),
            "group": notice.get("group", member.get("group", "")),
            "household": dispatch["household"],
            "planned_form_source": "发布单汇总数；未生成明细的计划份额不能指定到户",
            "actual_form": dispatch["form"],
            "channel": dispatch["channel"],
            "dispatch_state": dispatch["state"],
            "dispatch_registered_at": dispatch["registered_at"],
        }
        if receipt is None:
            details.append(
                {
                    **base,
                    "returned_at": "",
                    "receipt_registered_at": "",
                    "return_timing": "",
                    "disposition": "no_visible_receipt",
                    "disposition_label": "未回收或截至日尚不可见",
                    "included_in_indicator": False,
                    "exclusion_reason": "no_receipt_or_not_yet_registered",
                    "classification_status": "",
                    "target_barrier": "",
                }
            )
            continue

        classification = classify_response(
            form=dispatch["form"],
            state=receipt.get("state", "已答"),
            o1=receipt.get("o1", ""),
            n1=receipt.get("n1", ""),
            n2=receipt.get("n2", ""),
        )
        returned_date = parse_date(receipt.get("returned_at"))
        late = returned_date is not None and close_date is not None and returned_date > close_date
        if late:
            disposition = "late_return_processing_only"
            label = "超过回收期限：只计办理记录，不计当期指标"
            included = False
            reason = "returned_after_close"
        elif classification.status == "explicit_refusal":
            disposition = "explicit_refusal"
            label = "明确拒答，不计指标分母"
            included = False
            reason = "explicit_refusal"
        elif not classification.known_target:
            disposition = "returned_but_caliber_unusable"
            label = "已回收但不能判定联络/时段障碍，列入未明"
            included = False
            reason = classification.status
        else:
            disposition = "valid_indicator"
            label = "可用于当期口径统计"
            included = True
            reason = ""

        details.append(
            {
                **base,
                "returned_at": receipt.get("returned_at", ""),
                "receipt_registered_at": receipt.get("registered_at", ""),
                "return_timing": "逾期" if late else "按期",
                "disposition": disposition,
                "disposition_label": label,
                "included_in_indicator": included,
                "exclusion_reason": reason,
                "classification_status": classification.status,
                "target_barrier": "" if classification.target_barrier is None else int(classification.target_barrier),
            }
        )

    details_by_notice: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in details:
        details_by_notice[row["notice"]].append(row)

    notice_rows: list[dict[str, Any]] = []
    capacity_by_station = {c["station"]: c for c in ds.table("capacity.csv") if c.get("month") == month}
    for notice in notices:
        if notice.get("month") != month:
            continue
        nid = notice["notice"]
        rows = details_by_notice.get(nid, [])
        station = notice["station"]
        group = notice["group"]
        cap = capacity_by_station.get(station, {})
        agreed_o = as_int(notice.get("agreed_original"))
        agreed_n = as_int(notice.get("agreed_new"))
        actual_o = sum(1 for r in rows if r["actual_form"] == "原版")
        actual_n = sum(1 for r in rows if r["actual_form"] == "新版")
        unissued_o = max(0, agreed_o - actual_o)
        unissued_n = max(0, agreed_n - actual_n)
        disposition_counts = Counter(r["disposition"] for r in rows)
        valid = [r for r in rows if r["included_in_indicator"]]
        valid_original = [r for r in valid if r["actual_form"] == "原版"]
        valid_new = [r for r in valid if r["actual_form"] == "新版"]
        barriers = sum(1 for r in valid if r["target_barrier"] == 1)
        original_barriers = sum(1 for r in valid_original if r["target_barrier"] == 1)
        new_barriers = sum(1 for r in valid_new if r["target_barrier"] == 1)
        roster_n = sum(
            1
            for r in ds.table("roster.csv")
            if r["month"] == "2026-06" and r["station"] == station and r["group"] == group
        )
        booked_minutes = 0
        for dispatch in dispatches:
            if dispatch["notice"] != nid or dispatch["state"] != "已约":
                continue
            if dispatch["form"] == "原版":
                booked_minutes += as_int(cap.get("minutes_original"))
            else:
                booked_minutes += as_int(cap.get("minutes_new"))
        notice_rows.append(
            {
                "notice": nid,
                "station": station,
                "group": group,
                "notice_cutoff": notice["cutoff"],
                "applied_state": notice["applied_state"],
                "report_series": notice["report_series"],
                "roster_households": roster_n,
                "agreed_original": agreed_o,
                "agreed_new": agreed_n,
                "agreed_total": agreed_o + agreed_n,
                "actual_dispatches": len(rows),
                "actual_original": actual_o,
                "actual_new": actual_n,
                "unissued_original": unissued_o,
                "unissued_new": unissued_n,
                "unissued_total": unissued_o + unissued_n,
                "roster_not_covered_by_notice": max(0, roster_n - agreed_o - agreed_n),
                "valid_indicator_households": len(valid),
                "valid_barrier_households": barriers,
                "valid_barrier_rate": barriers / len(valid) if valid else None,
                "valid_original_households": len(valid_original),
                "original_barrier_households": original_barriers,
                "original_barrier_rate": original_barriers / len(valid_original) if valid_original else None,
                "valid_new_known_households": len(valid_new),
                "new_barrier_households": new_barriers,
                "new_known_barrier_rate": new_barriers / len(valid_new) if valid_new else None,
                "pooled_rate_interpretable_as_one_caliber": len({r["actual_form"] for r in valid}) <= 1,
                "commits_full_roster": agreed_o + agreed_n >= roster_n,
                "actual_dispatch_covers_full_roster": len(rows) >= roster_n,
                "may_report_full_group_switched": (
                    agreed_o == 0 and agreed_n >= roster_n and actual_n >= roster_n
                ),
                "no_visible_receipt": disposition_counts.get("no_visible_receipt", 0),
                "explicit_refusal": disposition_counts.get("explicit_refusal", 0),
                "caliber_unusable": disposition_counts.get("returned_but_caliber_unusable", 0),
                "late_processing_only": disposition_counts.get("late_return_processing_only", 0),
                "booked_interview_minutes": booked_minutes,
                "booked_interview_hours": round(booked_minutes / 60, 2),
            }
        )

    return ReconciliationResult(as_of=as_of, close_at=close_at, details=details, notices=notice_rows)


def station_capacity_table(ds: Dataset, month: str = "2026-07") -> list[dict[str, Any]]:
    comps = comparability_table(ds)
    failing_by_station = Counter(r["station"] for r in comps if not r["comparable"])
    dispatches = ds.table("july_dispatches.csv")
    notices = {n["notice"]: n for n in ds.table("notices.csv")}
    rows = []
    for cap in ds.find("capacity.csv", month=month):
        station = cap["station"]
        roster = [
            r for r in ds.table("roster.csv") if r["month"] == "2026-06" and r["station"] == station
        ]
        interview_only = sum(1 for r in roster if r["channel"] == "访谈")
        dual = sum(1 for r in roster if r["channel"] == "两用")
        capacity_minutes = as_int(cap["interview_hours"]) * 60
        min_o = as_int(cap["minutes_original"])
        min_n = as_int(cap["minutes_new"])
        max_original = capacity_minutes // min_o if min_o else 0
        booked_minutes = 0
        self_used = 0
        for d in dispatches:
            if notices.get(d["notice"], {}).get("station") != station:
                continue
            if d["state"] == "已约":
                booked_minutes += min_o if d["form"] == "原版" else min_n
            if d["channel"] == "自填":
                self_used += 1
        failing_groups = failing_by_station[station]
        group_count = sum(1 for r in comps if r["station"] == station)
        # Failing groups retain full original interviews; passing groups use
        # self-fill for dual-channel households and short interviews for the
        # interview-only households.
        coordinated_minutes = (
            failing_groups * 40 * min_o
            + (group_count - failing_groups) * 8 * min_n
        )
        coordinated_self = (group_count - failing_groups) * 32
        full_new_minutes = interview_only * min_n
        full_original_minutes = len(roster) * min_o
        rows.append(
            {
                "station": station,
                "month": month,
                "capacity_minutes": capacity_minutes,
                "capacity_hours": as_int(cap["interview_hours"]),
                "interview_only_households": interview_only,
                "dual_channel_households": dual,
                "max_original_interviews_stationwide": max_original,
                "equal_split_original_per_group": max_original // group_count if group_count else 0,
                "self_service_limit": as_int(cap["self_service_limit"]),
                "self_service_used_so_far": self_used,
                "booked_interview_minutes": booked_minutes,
                "booked_interview_hours": round(booked_minutes / 60, 2),
                "remaining_bookable_minutes": capacity_minutes - booked_minutes,
                "full_new_interview_minutes": full_new_minutes,
                "full_new_self_forms": dual,
                "full_new_capacity_ok": full_new_minutes <= capacity_minutes and dual <= as_int(cap["self_service_limit"]),
                "full_original_station_minutes": full_original_minutes,
                "full_original_station_capacity_ok": full_original_minutes <= capacity_minutes,
                "coordinated_plan_minutes": coordinated_minutes,
                "coordinated_plan_self_forms": coordinated_self,
                "coordinated_plan_capacity_ok": coordinated_minutes <= capacity_minutes and coordinated_self <= as_int(cap["self_service_limit"]),
                "failing_groups": failing_groups,
            }
        )
    return rows


def _full_new_channel_ready(ds: Dataset, station: str, group: str, capacity_row: dict[str, Any]) -> bool:
    members = [
        r
        for r in ds.table("roster.csv")
        if r["month"] == "2026-06" and r["station"] == station and r["group"] == group
    ]
    if not members:
        return False
    for member in members:
        channel = member.get("channel", "")
        interview_ready = "访谈" in channel or channel == "两用"
        self_ready = "自填" in channel or channel == "两用"
        # A household without self-fill can still use the new form by interview.
        if not (interview_ready or self_ready):
            return False
    self_forms = sum(1 for r in members if r.get("channel") == "两用")
    return self_forms <= as_int(capacity_row.get("self_service_limit"))


def station_group_decisions(ds: Dataset) -> list[dict[str, Any]]:
    current = {(r["station"], r["group"]): r for r in comparability_table(ds)}
    capacity = {r["station"]: r for r in station_capacity_table(ds)}
    reconciliation = {r["notice"]: r for r in reconcile_round(ds).notices}
    notices = ds.table("notices.csv")
    notice_by_key = {(n["station"], n["group"]): n for n in notices}
    cutoff_tables: dict[str, dict[tuple[str, str], dict[str, Any]]] = {}

    roster = {(r["month"], r["household"]): r for r in ds.table("roster.csv")}
    invitations = ds.table("invitations.csv")
    issue_key = {}
    for inv in invitations:
        member = roster.get((inv["month"], inv["household"]))
        if member:
            issue_key[inv["issue"]] = (member["station"], member["group"])

    rows = []
    for key, comp in sorted(current.items()):
        station, group = key
        cap = capacity[station]
        notice = notice_by_key.get(key)
        cutoff_comp = None
        unissued_new = 0
        booked_minutes = 0
        notice_id = ""
        cutoff = ""
        report_series = ""
        applied_state = ""
        if notice:
            notice_id = notice["notice"]
            cutoff = notice["cutoff"]
            report_series = notice["report_series"]
            applied_state = notice["applied_state"]
            if cutoff not in cutoff_tables:
                cutoff_tables[cutoff] = {
                    (r["station"], r["group"]): r
                    for r in comparability_table(ds, as_of=cutoff)
                }
            cutoff_comp = cutoff_tables[cutoff].get(key)
            rec = reconciliation.get(notice_id, {})
            unissued_new = rec.get("unissued_new", 0)
            booked_minutes = rec.get("booked_interview_minutes", 0)

        post_events = 0
        if cutoff:
            for c in ds.table("corrections.csv"):
                if issue_key.get(c["issue"]) == key and c["registered_at"] > cutoff:
                    post_events += 1
            for p in ds.table("permissions.csv"):
                if issue_key.get(p["issue"]) == key and p["decision"] == "撤回关联" and p["registered_at"] > cutoff:
                    post_events += 1

        qualified = comp["comparable"]
        coordinated_ok = cap["coordinated_plan_capacity_ok"]
        channel_ok = _full_new_channel_ready(ds, station, group, cap)
        full_switch_allowed = qualified and channel_ok and cap["full_new_capacity_ok"]
        interview_only = comp["interview_only_households"]
        dual = comp["dual_channel_households"]
        if full_switch_allowed:
            decision = "可签发整组新版并承诺趋势连续"
            plan_original = 0
            plan_new_interview = interview_only
            plan_new_self = dual
            trend_supported = True
        elif qualified and not full_switch_allowed:
            decision = "证据可比，但全组收发渠道/能力未核实可行：先补齐渠道，不得直接承诺整组切换"
            plan_original = comp["households"]
            plan_new_interview = 0
            plan_new_self = 0
            trend_supported = False
        elif coordinated_ok:
            decision = "口径不可比：若要承诺全组不断，下一轮应对全组保留原版访谈；也可双轨或明确重开序列"
            plan_original = comp["households"]
            plan_new_interview = 0
            plan_new_self = 0
            trend_supported = False
        else:
            coverable_original = min(comp["households"], cap["equal_split_original_per_group"])
            if coverable_original >= interview_only:
                plan_new_interview = 0
                plan_new_self = comp["households"] - coverable_original
            else:
                plan_new_interview = interview_only - coverable_original
                plan_new_self = dual
            decision = "口径不可比且访谈能力不足以原版覆盖全组：可维持均分的同口径可覆盖范围，或明确从本期重开序列"
            plan_original = coverable_original
            trend_supported = False

        suspend = bool(notice and not qualified and unissued_new > 0)
        if report_series == "单列":
            trend_commitment = "已明确单列/重开序列，不承诺旧趋势"
            trend_supported = True
        elif report_series == "继续":
            trend_commitment = "发布单承诺继续；当前证据支持" if qualified else "发布单写继续，但当前证据不足，不得对外承诺全组趋势"
            trend_supported = qualified
        else:
            trend_commitment = "未签趋势口径"

        rows.append(
            {
                "station": station,
                "group": group,
                "notice": notice_id,
                "notice_cutoff": cutoff,
                "applied_state": applied_state,
                "report_series": report_series,
                "current_comparable": qualified,
                "full_switch_allowed": full_switch_allowed,
                "full_group_channel_ready": channel_ok,
                "at_cutoff_comparable": cutoff_comp["comparable"] if cutoff_comp else "",
                "post_signing_permission_or_order_events": post_events,
                "policy_reasons": comp["reasons"],
                "decision": decision,
                "recommended_original_interviews": plan_original,
                "recommended_new_interviews": plan_new_interview,
                "recommended_new_self_forms": plan_new_self,
                "recommended_plan_total_forms": plan_original + plan_new_interview + plan_new_self,
                "restart_new_series_original_interviews": 0,
                "restart_new_series_new_interviews": interview_only,
                "restart_new_series_self_forms": dual,
                "station_coordinated_capacity_ok": coordinated_ok,
                "station_capacity_minutes": cap["capacity_minutes"],
                "coordinated_plan_minutes": cap["coordinated_plan_minutes"],
                "already_booked_notice_minutes": booked_minutes,
                "unissued_new_forms_to_suspend": unissued_new if suspend else 0,
                "suspend_unissued_switch_for_review": suspend,
                "trend_commitment_review": trend_commitment,
                "trend_promise_supported": trend_supported,
            }
        )
    return rows
