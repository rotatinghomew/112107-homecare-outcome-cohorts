from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from .classification import Classification, classify_reply
from .io import Dataset, as_float, as_int, parse_date

MISSING = Classification("missing_whole", "整份未回", None, False)
SINGLE_WITHDRAWN = Classification("single_use_withdrawn", "单份使用也被撤回", None, False)


def _d(value: Any):
    return parse_date(value) if not isinstance(value, type(None)) else None


def permission_state(
    permissions: list[dict[str, str]], issue: str, as_of: str | None = None
) -> dict[str, Any]:
    """Return the currently effective linkage and single-use permission.

    With an ``as_of`` date, only rows registered by that date are visible and
    only decisions effective by then govern linkage.  Without ``as_of``, all
    registered corrections/permissions are used for current reanalysis.
    """
    rows = [p for p in permissions if p.get("issue") == issue]
    cutoff = parse_date(as_of) if as_of else None
    if cutoff is not None:
        visible = [p for p in rows if (parse_date(p.get("registered_at")) or date_min()) <= cutoff]
        effective = [p for p in visible if (parse_date(p.get("effective_at")) or date_min()) <= cutoff]
        source = effective
    else:
        source = rows

    if not source:
        # Absence of a linkage grant means “do not link”.  Ordinary single
        # questionnaire processing remains allowed unless a row says otherwise.
        return {
            "pair_allowed": False,
            "single_use_allowed": True,
            "decision": "无关联授权",
            "effective_at": "",
            "registered_at": "",
        }

    latest = max(
        source,
        key=lambda p: (
            parse_date(p.get("effective_at")) or date_min(),
            parse_date(p.get("registered_at")) or date_min(),
        ),
    )
    single_text = latest.get("single_use", "") or ""
    single_allowed = not any(
        token in single_text for token in ("不保留", "撤回单份", "禁止", "不得单份")
    )
    if not single_text:
        single_allowed = True
    return {
        "pair_allowed": latest.get("decision") == "允许关联",
        "single_use_allowed": single_allowed,
        "decision": latest.get("decision", ""),
        "effective_at": latest.get("effective_at", ""),
        "registered_at": latest.get("registered_at", ""),
    }


def date_min():
    from datetime import date

    return date.min


def visible_correction(
    corrections: list[dict[str, str]], issue: str, as_of: str | None = None
) -> dict[str, str] | None:
    cutoff = parse_date(as_of) if as_of else None
    rows = [c for c in corrections if c.get("issue") == issue]
    if cutoff is not None:
        rows = [c for c in rows if (parse_date(c.get("registered_at")) or date_min()) <= cutoff]
    if not rows:
        return None
    return max(rows, key=lambda c: parse_date(c.get("registered_at")) or date_min())


def actual_first_form(
    invitation: dict[str, str],
    corrections: list[dict[str, str]],
    as_of: str | None = None,
) -> tuple[str, dict[str, str] | None]:
    correction = visible_correction(corrections, invitation["issue"], as_of)
    if correction:
        return correction["actual_first"], correction
    return invitation.get("sent_first", ""), None


def _reply_visible(reply: dict[str, str], as_of: str | None) -> bool:
    if as_of is None:
        return True
    cutoff = parse_date(as_of)
    received = parse_date(reply.get("received_at"))
    return received is not None and received <= cutoff


def primary_observations(
    ds: Dataset, month: str = "2026-06", as_of: str | None = None
) -> list[dict[str, Any]]:
    """One and only one primary indicator observation per roster household.

    The primary response is the version actually presented first.  If that
    response is missing, refused or unresolved, the second response is never
    used to fill its place.  Withdrawn linkage only removes pairing; a retained
    single-use first response still appears here.
    """
    roster = ds.find("roster.csv", month=month)
    invitations = ds.find("invitations.csv", month=month)
    inv_by_household = {r["household"]: r for r in invitations}
    replies_by_issue: dict[str, list[dict[str, str]]] = defaultdict(list)
    for reply in ds.table("replies.csv"):
        replies_by_issue[reply["issue"]].append(reply)
    corrections = ds.table("corrections.csv")
    permissions = ds.table("permissions.csv")

    observations: list[dict[str, Any]] = []
    for member in roster:
        household = member["household"]
        invitation = inv_by_household.get(household)
        if invitation is None:
            issue = ""
            actual_first = ""
            correction = None
            candidates = []
            perm = permission_state(permissions, "", as_of)
        else:
            issue = invitation["issue"]
            actual_first, correction = actual_first_form(invitation, corrections, as_of)
            visible_replies = [
                r for r in replies_by_issue.get(issue, []) if _reply_visible(r, as_of)
            ]
            candidates = [r for r in visible_replies if r.get("form") == actual_first]
            if not correction:
                first_order = [r for r in candidates if r.get("actual_order") == "1"]
                if first_order:
                    candidates = first_order
            perm = permission_state(permissions, issue, as_of)

        reply = candidates[0] if candidates else None
        if reply is None:
            classification = MISSING
        elif not perm["single_use_allowed"]:
            classification = SINGLE_WITHDRAWN
        else:
            classification = classify_reply(reply)

        observations.append(
            {
                "month": month,
                "station": member["station"],
                "group": member["group"],
                "channel": member["channel"],
                "household": household,
                "issue": issue,
                "design": invitation.get("design", "") if invitation else "",
                "assigned_first": invitation.get("assigned_first", "") if invitation else "",
                "actual_first": actual_first,
                "correction_applied": bool(correction),
                "adaptation_switch": bool(invitation and invitation.get("reason") == "适配转序"),
                "reply_form": reply.get("form", "") if reply else "",
                "actual_order": reply.get("actual_order", "") if reply else "",
                "received_at": reply.get("received_at", "") if reply else "",
                "status": classification.status,
                "status_label": classification.label,
                "target_barrier": classification.target_barrier,
                "known_target": classification.known_target,
                "single_use_allowed": perm["single_use_allowed"],
            }
        )
    return observations


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def summarize_observations(observations: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(o["status"] for o in observations)
    barrier = sum(1 for o in observations if o["status"] == "barrier")
    no_barrier = sum(1 for o in observations if o["status"] == "no_barrier")
    other = sum(1 for o in observations if o["status"] == "other_reason_original")
    known = barrier + no_barrier + other
    refused = counts.get("explicit_refusal", 0)
    missing = counts.get("missing_whole", 0)
    unresolved = sum(
        count
        for status, count in counts.items()
        if status.startswith("unresolved") or status in {"invalid_form", "single_use_withdrawn"}
    )
    unavailable = refused + missing + unresolved
    n = len(observations)
    return {
        "households": n,
        "known_target_households": known,
        "barrier_households": barrier,
        "no_barrier_households": no_barrier,
        "other_reason_households": other,
        "refused_households": refused,
        "missing_households": missing,
        "unresolved_answer_households": unresolved,
        "unavailable_households": unavailable,
        "barrier_rate": _rate(barrier, known),
        "unresolved_rate": _rate(unavailable, n),
        "response_rate": _rate(known, n),
        "lower_bound_all_assigned": _rate(barrier, n),
        "upper_bound_all_assigned": _rate(barrier + unavailable, n),
    }


def cell_indicator_table(
    ds: Dataset, month: str = "2026-06", as_of: str | None = None
) -> list[dict[str, Any]]:
    observations = primary_observations(ds, month=month, as_of=as_of)
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for obs in observations:
        groups[(obs["station"], obs["group"])].append(obs)
    total_households = len(observations)
    rows: list[dict[str, Any]] = []
    for (station, group), items in sorted(groups.items()):
        summary = summarize_observations(items)
        channel_counts = Counter(o["channel"] for o in items)
        rows.append(
            {
                "station": station,
                "group": group,
                "month": month,
                "district_weight": summary["households"] / total_households if total_households else None,
                "dual_channel_households": channel_counts.get("两用", 0),
                "interview_only_households": channel_counts.get("访谈", 0),
                **summary,
            }
        )
    return rows


def indicator_strata_table(
    ds: Dataset, month: str = "2026-06", as_of: str | None = None
) -> list[dict[str, Any]]:
    """Split primary indicators by channel and trial/regular design."""
    observations = primary_observations(ds, month=month, as_of=as_of)
    groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for obs in observations:
        groups[(obs["station"], obs["group"], obs["channel"], obs["design"])].append(obs)
    rows = []
    for (station, group, channel, design), items in sorted(groups.items()):
        summary = summarize_observations(items)
        rows.append(
            {
                "station": station,
                "group": group,
                "channel": channel,
                "design": design,
                "stratum": ("两用随机试填组" if channel == "两用" and design == "随机次序"
                            else "只能访谈组/常规原版" if channel == "访谈"
                            else "两用常规单版组"),
                **summary,
            }
        )
    return rows


def assigned_arm_table(
    ds: Dataset, month: str = "2026-06", as_of: str | None = None
) -> list[dict[str, Any]]:
    """Visible results by original randomized arm, despite later reordering."""
    observations = primary_observations(ds, month=month, as_of=as_of)
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for obs in observations:
        if obs["design"] == "随机次序" and obs["assigned_first"]:
            groups[(obs["station"], obs["group"], obs["assigned_first"])].append(obs)
    rows = []
    for (station, group, assigned_first), items in sorted(groups.items()):
        summary = summarize_observations(items)
        rows.append(
            {
                "station": station,
                "group": group,
                "assigned_first": assigned_first,
                "assigned_households": len(items),
                "adaptation_switches": sum(o["adaptation_switch"] for o in items),
                "corrected_orders": sum(o["correction_applied"] for o in items),
                "actual_first_original": sum(o["actual_first"] == "原版" for o in items),
                "actual_first_new": sum(o["actual_first"] == "新版" for o in items),
                **summary,
            }
        )
    return rows


def pair_records(ds: Dataset, as_of: str | None = None) -> list[dict[str, Any]]:
    """Return authorized, currently linkable binary crossover pairs only."""
    invitations = ds.find("invitations.csv", month="2026-06")
    replies_by_issue: dict[str, list[dict[str, str]]] = defaultdict(list)
    for reply in ds.table("replies.csv"):
        replies_by_issue[reply["issue"]].append(reply)
    corrections = ds.table("corrections.csv")
    permissions = ds.table("permissions.csv")
    roster = {(r["month"], r["household"]): r for r in ds.table("roster.csv")}

    pairs: list[dict[str, Any]] = []
    for inv in invitations:
        if inv.get("design") != "随机次序":
            continue
        issue = inv["issue"]
        perm = permission_state(permissions, issue, as_of)
        if not perm["pair_allowed"]:
            continue
        actual_first, correction = actual_first_form(inv, corrections, as_of)
        visible_replies = [
            r for r in replies_by_issue.get(issue, []) if _reply_visible(r, as_of)
        ]
        by_form = {r["form"]: classify_reply(r) for r in visible_replies}
        original = by_form.get("原版")
        new = by_form.get("新版")
        if original is None or new is None:
            continue
        if not original.known_target or not new.known_target:
            continue
        member = roster[("2026-06", inv["household"])]
        actual_second = "新版" if actual_first == "原版" else "原版"
        pairs.append(
            {
                "station": member["station"],
                "group": member["group"],
                "household": inv["household"],
                "issue": issue,
                "old": 1 if original.target_barrier else 0,
                "new": 1 if new.target_barrier else 0,
                "sequence_actual": f"{actual_first}→{actual_second}",
                "sequence_assigned": f"{inv['assigned_first']}→{'新版' if inv['assigned_first'] == '原版' else '原版'}",
                "adaptation_switch": inv.get("reason") == "适配转序",
                "order_corrected": bool(correction),
            }
        )
    return pairs


def _sequence_contrast(pairs: list[dict[str, Any]], sequence_field: str) -> dict[str, Any]:
    groups: dict[str, list[float]] = defaultdict(list)
    counts: dict[str, int] = defaultdict(int)
    first_outcomes: list[int] = []
    second_outcomes: list[int] = []
    for pair in pairs:
        first_form = pair[sequence_field].split("→")[0]
        first = pair["old"] if first_form == "原版" else pair["new"]
        second = pair["new"] if first_form == "原版" else pair["old"]
        first_outcomes.append(first)
        second_outcomes.append(second)
        key = "原版先" if first_form == "原版" else "新版先"
        groups[key].append(pair["new"] - pair["old"])
        counts[key] += 1
    old_first = sum(groups["原版先"]) / len(groups["原版先"]) if groups["原版先"] else None
    new_first = sum(groups["新版先"]) / len(groups["新版先"]) if groups["新版先"] else None
    effect = abs(old_first - new_first) if old_first is not None and new_first is not None else None
    first_rate = sum(first_outcomes) / len(first_outcomes) if first_outcomes else None
    second_rate = sum(second_outcomes) / len(second_outcomes) if second_outcomes else None
    return {
        "order_effect": effect,
        "pooled_first_rate": first_rate,
        "pooled_second_rate": second_rate,
        "pooled_order_effect": abs(first_rate - second_rate) if first_rate is not None and second_rate is not None else None,
        "old_first_new_minus_old": old_first,
        "new_first_new_minus_old": new_first,
        "old_first_pairs": counts["原版先"],
        "new_first_pairs": counts["新版先"],
    }


def pair_evidence_table(ds: Dataset, as_of: str | None = None) -> list[dict[str, Any]]:
    invitations = ds.find("invitations.csv", month="2026-06")
    roster = {(r["month"], r["household"]): r for r in ds.table("roster.csv")}
    permissions = ds.table("permissions.csv")
    replies_by_issue: dict[str, list[dict[str, str]]] = defaultdict(list)
    for reply in ds.table("replies.csv"):
        replies_by_issue[reply["issue"]].append(reply)
    all_pairs = pair_records(ds, as_of)
    grouped_pairs: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for pair in all_pairs:
        grouped_pairs[(pair["station"], pair["group"])].append(pair)

    random_groups: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for inv in invitations:
        if inv.get("design") == "随机次序":
            member = roster[("2026-06", inv["household"])]
            random_groups[(member["station"], member["group"])].append(inv)

    rows = []
    for key in sorted(random_groups):
        invs = random_groups[key]
        pairs = grouped_pairs.get(key, [])
        n = len(pairs)
        old_rate = _rate(sum(p["old"] for p in pairs), n)
        new_rate = _rate(sum(p["new"] for p in pairs), n)
        bias = (new_rate - old_rate) if new_rate is not None and old_rate is not None else None
        actual_order = _sequence_contrast(pairs, "sequence_actual")
        assigned_order = _sequence_contrast(pairs, "sequence_assigned")
        withdrawn = 0
        permissioned = 0
        second_received = 0
        second_refused = 0
        for inv in invs:
            state = permission_state(permissions, inv["issue"], as_of)
            if state["pair_allowed"]:
                permissioned += 1
            elif state["decision"] == "撤回关联":
                withdrawn += 1
            second_rows = [r for r in replies_by_issue.get(inv["issue"], []) if r.get("actual_order") == "2"]
            if second_rows:
                second_received += 1
                if any(r.get("state") == "拒答" for r in second_rows):
                    second_refused += 1
        rows.append(
            {
                "station": key[0],
                "group": key[1],
                "random_assigned_households": len(invs),
                "second_copy_received": second_received,
                "second_copy_missing": len(invs) - second_received,
                "second_copy_refused": second_refused,
                "permissioned_households": permissioned,
                "withdrawn_links_visible": withdrawn,
                "analyzable_pairs": n,
                "old_barrier_rate_paired": old_rate,
                "new_barrier_rate_paired": new_rate,
                "version_bias_new_minus_old": bias,
                "version_bias_abs": abs(bias) if bias is not None else None,
                "discordant_pairs": sum(1 for p in pairs if p["old"] != p["new"]),
                "adaptation_switches_in_pairs": sum(p["adaptation_switch"] for p in pairs),
                "corrected_pairs": sum(p["order_corrected"] for p in pairs),
                **{f"actual_{k}": v for k, v in actual_order.items()},
                **{f"assigned_{k}": v for k, v in assigned_order.items()},
            }
        )
    return rows


def _policy(ds: Dataset, policy: str | None = None) -> dict[str, str]:
    rows = ds.table("criteria.csv")
    if policy:
        return next(r for r in rows if r["policy"] == policy)
    return rows[0]


def comparability_table(
    ds: Dataset, as_of: str | None = None, policy: str | None = None
) -> list[dict[str, Any]]:
    criteria = _policy(ds, policy)
    min_pairs = as_int(criteria["min_pairs"])
    max_bias = as_float(criteria["max_bias"])
    max_order = as_float(criteria["max_order_effect"])
    max_unresolved = as_float(criteria["max_unresolved"])

    indicators = {(r["station"], r["group"]): r for r in cell_indicator_table(ds, "2026-06", as_of)}
    pairs = {(r["station"], r["group"]): r for r in pair_evidence_table(ds, as_of)}
    rows = []
    for key, ind in sorted(indicators.items()):
        pe = pairs[key]
        pair_ok = pe["analyzable_pairs"] >= min_pairs
        bias_ok = pe["version_bias_abs"] is not None and pe["version_bias_abs"] <= max_bias
        actual_oe = pe["actual_order_effect"]
        assigned_oe = pe["assigned_order_effect"]
        order_values = [v for v in (actual_oe, assigned_oe) if v is not None]
        order_policy = max(order_values) if order_values else None
        order_ok = order_policy is not None and order_policy <= max_order
        unresolved_ok = ind["unresolved_rate"] is not None and ind["unresolved_rate"] <= max_unresolved
        reasons = []
        if not pair_ok:
            reasons.append(f"成对份数{pe['analyzable_pairs']}<{min_pairs}")
        if not bias_ok:
            reasons.append(
                f"换版偏差{pe['version_bias_abs']:.4f}>{max_bias:.2f}"
                if pe["version_bias_abs"] is not None
                else "无法计算换版偏差"
            )
        if not order_ok:
            reasons.append(f"次序效应{order_policy:.4f}>{max_order:.2f}")
        if not unresolved_ok:
            reasons.append(f"未明比例{ind['unresolved_rate']:.4f}>{max_unresolved:.2f}")
        comparable = pair_ok and bias_ok and order_ok and unresolved_ok
        rows.append(
            {
                "station": key[0],
                "group": key[1],
                "as_of": as_of or "当前全部已登记记录",
                "comparable": comparable,
                "decision": "可比，可在交代范围与权重后连接趋势" if comparable else "不可直接连接全组趋势",
                "reasons": "；".join(reasons) if reasons else "成对支持量、换版偏差、次序效应和未明比例均在政策限内",
                "min_pairs": min_pairs,
                "max_bias": max_bias,
                "max_order_effect": max_order,
                "max_unresolved": max_unresolved,
                "order_effect_policy": order_policy,
                **ind,
                **{f"pair_{k}": v for k, v in pe.items() if k not in {"station", "group"}},
            }
        )
    return rows


def trend_table(ds: Dataset, as_of: str | None = None) -> list[dict[str, Any]]:
    current = {(r["station"], r["group"]): r for r in comparability_table(ds, as_of)}
    jan = {(r["station"], r["group"]): r for r in cell_indicator_table(ds, "2026-01")}
    archive = ds.table("archive_reports.csv")
    official_jan: dict[tuple[str, str], dict[str, str]] = {}
    published_june: dict[tuple[str, str], dict[str, str]] = {}
    for report in archive:
        key = (report["station"], report["group"])
        if report["period"] == "2026-01":
            official_jan[key] = report
        if report["period"] == "2026-06":
            published_june[key] = report

    rows = []
    for key, cur in sorted(current.items()):
        old = jan[key]
        raw_change = (
            cur["barrier_rate"] - old["barrier_rate"]
            if cur["barrier_rate"] is not None and old["barrier_rate"] is not None
            else None
        )
        official = official_jan.get(key)
        official_rate = None
        official_change = None
        if official:
            official_rate = as_int(official["barrier_households"]) / as_int(official["households"])
            official_change = cur["barrier_rate"] - official_rate if cur["barrier_rate"] is not None else None
        june_pub = published_june.get(key)
        rows.append(
            {
                "station": key[0],
                "group": key[1],
                "comparable": cur["comparable"],
                "policy_reasons": cur["reasons"],
                "jan_raw_households": old["known_target_households"],
                "jan_raw_barrier": old["barrier_households"],
                "jan_raw_rate": old["barrier_rate"],
                "june_households": cur["known_target_households"],
                "june_barrier": cur["barrier_households"],
                "june_rate": cur["barrier_rate"],
                "raw_change_pp": raw_change,
                "archive_jan_report": official["report"] if official else "",
                "archive_jan_households": official["households"] if official else "",
                "archive_jan_barrier": official["barrier_households"] if official else "",
                "archive_jan_rate": official_rate,
                "archive_change_pp": official_change,
                "archive_june_report": june_pub["report"] if june_pub else "",
                "archive_june_scope": june_pub["scope"] if june_pub else "",
                "can_connect_raw_trend": cur["comparable"],
                "can_connect_published_archive": cur["comparable"] and official is not None,
                "trend_statement": _trend_statement(cur["comparable"], raw_change, official_change),
            }
        )
    return rows


def _trend_statement(comparable: bool, raw_change: float | None, archive_change: float | None) -> str:
    if not comparable:
        return "换版/次序证据未过政策门槛：不得把本期率与历史率直接连接，也不得归因于服务改善或恶化"
    if raw_change is None:
        return "证据不足，无法判断趋势"
    if raw_change <= -0.09:
        direction = "下降并超过换版容许偏差，支持求助变方便"
    elif raw_change >= 0.09:
        direction = "上升并超过换版容许偏差，提示求助更困难"
    elif raw_change < 0:
        direction = "小幅下降，但未超过容许偏差，宜表述为基本稳定"
    elif raw_change > 0:
        direction = "小幅上升，但未超过容许偏差，宜表述为基本稳定"
    else:
        direction = "完全持平"
    return "可比口径下：" + direction


def region_scope_table(ds: Dataset, as_of: str | None = None) -> list[dict[str, Any]]:
    comps = comparability_table(ds, as_of)
    total_hh = sum(r["households"] for r in comps)

    def aggregate(name: str, rows: list[dict[str, Any]], connectable: bool, note: str):
        hh = sum(r["households"] for r in rows)
        known = sum(r["known_target_households"] for r in rows)
        barrier = sum(r["barrier_households"] for r in rows)
        unavailable = sum(r["unavailable_households"] for r in rows)
        jan_rows = cell_indicator_table(ds, "2026-01")
        jan_index = {(r["station"], r["group"]): r for r in jan_rows}
        jan_known = sum(jan_index[(r["station"], r["group"])]["known_target_households"] for r in rows)
        jan_barrier = sum(jan_index[(r["station"], r["group"])]["barrier_households"] for r in rows)
        cur_rate = _rate(barrier, known)
        jan_rate = _rate(jan_barrier, jan_known)
        return {
            "scope": name,
            "cells": "；".join(f"{r['station']}{r['group']}" for r in rows),
            "roster_households": hh,
            "district_weight": hh / total_hh if total_hh else None,
            "june_known_households": known,
            "june_barrier_households": barrier,
            "june_rate": cur_rate,
            "jan_raw_known_households": jan_known,
            "jan_raw_barrier_households": jan_barrier,
            "jan_raw_rate": jan_rate,
            "raw_change_pp": cur_rate - jan_rate if cur_rate is not None and jan_rate is not None else None,
            "unavailable_households": unavailable,
            "trend_connectable": connectable,
            "note": note,
        }

    qualified = [r for r in comps if r["comparable"]]
    unqualified = [r for r in comps if not r["comparable"]]
    all_row = aggregate(
        "全区全部范围（仅列示，不可连接趋势）",
        comps,
        False,
        "四个组未过换版/次序门槛；混合率受口径和构成影响，不能作为全区趋势承诺。",
    )
    comparable_row = aggregate(
        "经政策判定可比的范围",
        qualified,
        True,
        "仅这些站组可在各自范围内连接原始名册重算基线；权重为名册户数。",
    )
    incomparable_row = aggregate(
        "不可比、需双轨或单列新序列的范围",
        unqualified,
        False,
        "须单独列示权重、拒答、失访和证据不足，不能由区级数值倒推站点合格。",
    )
    archive = ds.table("archive_reports.csv")
    archive_keys = {(r["station"], r["group"]) for r in archive if r["period"] == "2026-01"}
    official_linkable = [r for r in qualified if (r["station"], r["group"]) in archive_keys]
    archive_row = aggregate(
        "其中可连接旧公报2026-01数值的范围",
        official_linkable,
        bool(official_linkable),
        "旧公报数值保持原样，不用当前记录回写；其余可比组只有原始答卷基线。",
    )
    return [comparable_row, incomparable_row, archive_row, all_row]
