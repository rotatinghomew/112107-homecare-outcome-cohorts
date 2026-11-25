from __future__ import annotations

from dataclasses import dataclass

TARGET_VALUES = {"联络", "时段"}
REFUSAL_TOKENS = {"拒答", "明确拒答", "拒绝回答"}


@dataclass(frozen=True)
class Classification:
    status: str
    label: str
    target_barrier: bool | None
    known_target: bool

    @property
    def counts_as_barrier(self) -> bool:
        return self.target_barrier is True


def _values(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(";") if part.strip()]


def _is_refusal(state: str | None, *items: str | None) -> bool:
    if (state or "").strip() in REFUSAL_TOKENS:
        return True
    return any((item or "").strip() in REFUSAL_TOKENS for item in items)


def classify_response(
    form: str,
    state: str | None = "已答",
    o1: str | None = "",
    n1: str | None = "",
    n2: str | None = "",
) -> Classification:
    """Classify one returned questionnaire.

    A missing row is handled by the caller as ``missing_whole``.  This function
    separates explicit refusal, a known negative, a target barrier, and an
    answered-but-unresolved contact/time status.
    """
    if _is_refusal(state, o1, n1, n2):
        return Classification("explicit_refusal", "明确拒答", None, False)

    if form == "原版":
        values = _values(o1)
        if not values:
            return Classification("unresolved_blank", "已收回但关键题空白", None, False)
        if any(v in TARGET_VALUES for v in values):
            return Classification("barrier", "有联络或时段障碍", True, True)
        if "无" in values:
            return Classification("no_barrier", "答称没有困难", False, True)
        if all(v == "其他" for v in values):
            # The original is a multi-select checklist.  An explicit “other”
            # only is a known non-target answer, but is not “no difficulty”.
            return Classification(
                "other_reason_original", "原版仅填其他原因", False, True
            )
        return Classification("unresolved_answer", "答案无法归入指标口径", None, False)

    if form == "新版":
        if (n1 or "").strip() == "否":
            # n2 is intentionally not asked after “no”.  A stray value must
            # not turn this into a missing/unresolved response.
            return Classification("no_barrier", "答称未遇到障碍", False, True)
        if (n1 or "").strip() == "是":
            values = _values(n2)
            if any(v in TARGET_VALUES for v in values):
                return Classification("barrier", "有联络或时段障碍", True, True)
            if not values:
                return Classification(
                    "unresolved_new_reason_blank",
                    "称有障碍但未写原因，不能判为无联络/时段障碍",
                    None,
                    False,
                )
            # n2 asks for the *main* obstacle.  “Other” alone does not prove
            # that a contact/time obstacle was absent.
            return Classification(
                "unresolved_new_other_primary",
                "仅写另一个主要原因，不能排除联络/时段障碍",
                None,
                False,
            )
        if not (n1 or "").strip():
            return Classification("unresolved_blank", "已收回但n1空白", None, False)
        return Classification("unresolved_answer", "答案无法归入指标口径", None, False)

    return Classification("invalid_form", f"未知版本：{form}", None, False)


def classify_reply(reply: dict[str, str]) -> Classification:
    return classify_response(
        form=reply.get("form", ""),
        state=reply.get("state", "已答"),
        o1=reply.get("o1", ""),
        n1=reply.get("n1", ""),
        n2=reply.get("n2", ""),
    )
