import tempfile
import unittest
from pathlib import Path

from survey_center import (
    cell_indicator_table,
    comparability_table,
    load_dataset,
    pair_evidence_table,
    pair_records,
    permission_state,
    primary_observations,
    reconcile_round,
    station_group_decisions,
)
from survey_center.analysis import trend_table
from survey_center.classification import classify_response
from survey_center.io import Dataset
from survey_center.operations import station_capacity_table
from survey_center.reports import publish_snapshot

ROOT = Path(__file__).resolve().parents[1]


class ClassificationTests(unittest.TestCase):
    def test_missing_refusal_no_difficulty_and_target_are_distinct(self):
        self.assertEqual(classify_response("原版", state="拒答").status, "explicit_refusal")
        self.assertEqual(classify_response("原版", o1="无").status, "no_barrier")
        self.assertEqual(classify_response("原版", o1="联络;时段").status, "barrier")
        self.assertEqual(classify_response("新版", n1="否").status, "no_barrier")

    def test_new_yes_without_contact_reason_is_not_negative(self):
        blank = classify_response("新版", n1="是", n2="")
        other = classify_response("新版", n1="是", n2="其他")
        self.assertFalse(blank.known_target)
        self.assertIsNone(blank.target_barrier)
        self.assertEqual(blank.status, "unresolved_new_reason_blank")
        self.assertFalse(other.known_target)
        self.assertEqual(other.status, "unresolved_new_other_primary")

    def test_new_no_does_not_require_n2(self):
        result = classify_response("新版", n1="否", n2="")
        self.assertTrue(result.known_target)
        self.assertFalse(result.target_barrier)


class PrimaryAndPermissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ds = load_dataset(ROOT)

    def test_each_household_has_one_june_observation(self):
        obs = primary_observations(self.ds)
        self.assertEqual(len(obs), 240)
        keys = [(o["station"], o["month"], o["household"]) for o in obs]
        self.assertEqual(len(keys), len(set(keys)))

    def test_trial_and_interview_only_strata_are_separated(self):
        from survey_center import indicator_strata_table

        strata = indicator_strata_table(self.ds)
        totals = {}
        for row in strata:
            key = (row["channel"], row["design"])
            totals[key] = totals.get(key, 0) + row["households"]
        self.assertEqual(totals[("两用", "随机次序")], 180)
        self.assertEqual(totals[("访谈", "常规")], 48)
        self.assertEqual(totals[("两用", "常规")], 12)

    def test_second_response_does_not_fill_missing_first(self):
        ds = Dataset(
            root=Path("."),
            contract={},
            tables={
                "roster.csv": [
                    {"month": "2026-06", "household": "HX", "station": "S", "group": "G", "channel": "两用"}
                ],
                "invitations.csv": [
                    {
                        "month": "2026-06",
                        "household": "HX",
                        "issue": "IX",
                        "assigned_first": "原版",
                        "sent_first": "原版",
                        "design": "随机次序",
                        "reason": "",
                    }
                ],
                "replies.csv": [
                    {"issue": "IX", "form": "新版", "actual_order": "2", "state": "已答",
                     "received_at": "2026-06-12", "o1": "", "n1": "否", "n2": ""}
                ],
                "corrections.csv": [],
                "permissions.csv": [],
            },
        )
        obs = primary_observations(ds)
        self.assertEqual(obs[0]["status"], "missing_whole")
        self.assertEqual(obs[0]["reply_form"], "")

    def test_refused_first_is_not_replaced_by_valid_second(self):
        ds = Dataset(
            root=Path("."),
            contract={},
            tables={
                "roster.csv": [
                    {"month": "2026-06", "household": "HX", "station": "S", "group": "G", "channel": "两用"}
                ],
                "invitations.csv": [
                    {"month": "2026-06", "household": "HX", "issue": "IX", "sent_first": "原版",
                     "assigned_first": "原版", "design": "随机次序", "reason": ""}
                ],
                "replies.csv": [
                    {"issue": "IX", "form": "原版", "actual_order": "1", "state": "拒答",
                     "received_at": "2026-06-11", "o1": "", "n1": "", "n2": ""},
                    {"issue": "IX", "form": "新版", "actual_order": "2", "state": "已答",
                     "received_at": "2026-06-12", "o1": "", "n1": "否", "n2": ""},
                ],
                "corrections.csv": [],
                "permissions.csv": [],
            },
        )
        obs = primary_observations(ds)
        self.assertEqual(obs[0]["status"], "explicit_refusal")

    def test_withdrawn_pair_excluded_but_single_first_use_remains(self):
        current_pairs = {(p["station"], p["group"], p["household"]) for p in pair_records(self.ds)}
        self.assertNotIn(("河东", "持续照护", "H003"), current_pairs)
        self.assertNotIn(("新桥", "持续照护", "H083"), current_pairs)

        obs = {(o["station"], o["group"], o["household"]): o for o in primary_observations(self.ds)}
        h003 = obs[("河东", "持续照护", "H003")]
        h083 = obs[("新桥", "持续照护", "H083")]
        self.assertEqual(h003["actual_first"], "新版")
        self.assertEqual(h003["status"], "no_barrier")
        self.assertEqual(h083["status"], "barrier")

        state = permission_state(self.ds.table("permissions.csv"), "I1H003")
        self.assertFalse(state["pair_allowed"])
        self.assertTrue(state["single_use_allowed"])

    def test_correction_changes_actual_first_only_after_registration(self):
        current = {o["household"]: o for o in primary_observations(self.ds)}
        initial = {o["household"]: o for o in primary_observations(self.ds, as_of="2026-07-01")}
        self.assertEqual(current["H004"]["actual_first"], "原版")
        self.assertTrue(current["H004"]["correction_applied"])
        self.assertEqual(initial["H004"]["actual_first"], "新版")
        self.assertFalse(initial["H004"]["correction_applied"])


class ComparabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ds = load_dataset(ROOT)
        cls.rows = {(r["station"], r["group"]): r for r in comparability_table(cls.ds)}

    def test_exact_june_cell_counts(self):
        for row in cell_indicator_table(self.ds):
            self.assertEqual(row["households"], 40)
            self.assertEqual(row["known_target_households"], 35)
            self.assertEqual(row["unavailable_households"], 5)
            self.assertAlmostEqual(row["unresolved_rate"], 0.125)

    def test_policy_decisions_match_designed_threshold_cases(self):
        expected = {
            ("河东", "日常协助"): False,  # bias 2/21 = 9.52% > 9%
            ("河东", "持续照护"): True,
            ("新桥", "日常协助"): False,  # order effect > 10%
            ("新桥", "持续照护"): True,
            ("北苑", "日常协助"): False,
            ("北苑", "持续照护"): False,  # bias 12% > 9%
        }
        for key, expected_value in expected.items():
            with self.subTest(key=key):
                self.assertIs(self.rows[key]["comparable"], expected_value)

    def test_district_cannot_be_used_to_reverse_station_decisions(self):
        from survey_center import region_scope_table

        regions = {r["scope"]: r for r in region_scope_table(self.ds)}
        comparable = regions["经政策判定可比的范围"]
        incomparable = regions["不可比、需双轨或单列新序列的范围"]
        self.assertEqual(comparable["roster_households"], 80)
        self.assertAlmostEqual(comparable["district_weight"], 1 / 3)
        self.assertEqual(incomparable["roster_households"], 160)
        self.assertAlmostEqual(incomparable["district_weight"], 2 / 3)
        all_scope = regions["全区全部范围（仅列示，不可连接趋势）"]
        self.assertFalse(all_scope["trend_connectable"])


class JulyReconciliationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ds = load_dataset(ROOT)
        cls.current = reconcile_round(cls.ds)
        cls.initial = reconcile_round(cls.ds, as_of="2026-08-01")

    def test_current_dispositions_separate_all_categories(self):
        self.assertEqual(len(self.current.details), 24)
        by_receipt = {r["receipt"]: r for r in self.current.details}
        self.assertTrue(by_receipt["J01"]["included_in_indicator"])
        self.assertTrue(by_receipt["J13"]["included_in_indicator"])
        self.assertEqual(by_receipt["J03"]["disposition"], "explicit_refusal")
        self.assertEqual(by_receipt["J10"]["disposition"], "returned_but_caliber_unusable")
        self.assertEqual(by_receipt["J11"]["disposition"], "returned_but_caliber_unusable")
        self.assertEqual(by_receipt["J14"]["disposition"], "late_return_processing_only")
        self.assertFalse(by_receipt["J14"]["included_in_indicator"])
        missing = [r for r in self.current.details if r["disposition"] == "no_visible_receipt"]
        self.assertEqual(len(missing), 16)
        valid = [r for r in self.current.details if r["included_in_indicator"]]
        self.assertEqual(len(valid), 4)

    def test_late_registered_ontime_return_is_invisible_initially_but_kept_in_round(self):
        initial_by_receipt = {r["receipt"]: r for r in self.initial.details}
        # The dispatch/receipt label exists, but the later-registered receipt
        # payload was not visible at the initial knowledge cutoff.
        self.assertEqual(initial_by_receipt["J13"]["disposition"], "no_visible_receipt")
        self.assertEqual(initial_by_receipt["J13"]["returned_at"], "")
        self.assertFalse(initial_by_receipt["J13"]["included_in_indicator"])
        n3_initial = next(n for n in self.initial.notices if n["notice"] == "N3")
        self.assertEqual(n3_initial["actual_dispatches"], 12)
        self.assertEqual(n3_initial["valid_indicator_households"], 0)
        self.assertEqual(n3_initial["no_visible_receipt"], 12)

        current_j13 = next(r for r in self.current.details if r["receipt"] == "J13")
        self.assertEqual(current_j13["return_timing"], "按期")
        self.assertTrue(current_j13["included_in_indicator"])

    def test_unissued_notice_shares_are_counted_separately(self):
        notices = {n["notice"]: n for n in self.current.notices}
        self.assertEqual(notices["N1"]["unissued_new"], 20)
        self.assertEqual(notices["N2"]["unissued_total"], 32)
        self.assertEqual(notices["N3"]["actual_dispatches"], 12)
        self.assertEqual(notices["N3"]["unissued_total"], 0)

    def test_snapshot_file_is_not_silently_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = publish_snapshot(self.ds, "2026-08-01", tmp)
            self.assertTrue(first["markdown"].exists())
            with self.assertRaises(FileExistsError):
                publish_snapshot(self.ds, "2026-08-01", tmp)


class DispatchDecisionAndArchiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ds = load_dataset(ROOT)
        cls.decisions = {(r["station"], r["group"]): r for r in station_group_decisions(cls.ds)}

    def test_full_new_issuance_is_guarded_by_evidence(self):
        from survey_center.issuance import IssuanceError, draft_arrangement

        n2 = draft_arrangement(self.ds, "新桥", "持续照护", "full_new")
        self.assertTrue(n2.trend_continuity_promised)
        self.assertEqual(n2.total_forms, 40)
        with self.assertRaises(IssuanceError):
            draft_arrangement(self.ds, "河东", "日常协助", "full_new")
        restart = draft_arrangement(self.ds, "河东", "日常协助", "restart_new")
        self.assertFalse(restart.trend_continuity_promised)
        self.assertEqual(restart.total_forms, 40)

    def test_n1_unsupported_trend_suspends_unissued_switch(self):
        n1 = self.decisions[("河东", "日常协助")]
        self.assertTrue(n1["suspend_unissued_switch_for_review"])
        self.assertFalse(n1["trend_promise_supported"])
        self.assertEqual(n1["unissued_new_forms_to_suspend"], 20)

    def test_n2_remains_supported_after_withdrawal(self):
        n2 = self.decisions[("新桥", "持续照护")]
        self.assertTrue(n2["current_comparable"])
        self.assertFalse(n2["suspend_unissued_switch_for_review"])
        self.assertIn("当前证据支持", n2["trend_commitment_review"])

    def test_beiyuan_capacity_constraint(self):
        cap = {r["station"]: r for r in station_capacity_table(self.ds)}["北苑"]
        self.assertEqual(cap["max_original_interviews_stationwide"], 34)
        self.assertEqual(cap["equal_split_original_per_group"], 17)
        self.assertFalse(cap["coordinated_plan_capacity_ok"])
        n3 = self.decisions[("北苑", "持续照护")]
        self.assertIn("能力不足", n3["decision"])
        self.assertEqual(n3["recommended_plan_total_forms"], 40)
        self.assertEqual(n3["recommended_original_interviews"], 17)
        self.assertEqual(n3["recommended_new_self_forms"], 23)

    def test_qualified_cell_plan_covers_full_roster(self):
        n2 = self.decisions[("新桥", "持续照护")]
        self.assertTrue(n2["full_switch_allowed"])
        self.assertEqual(n2["recommended_plan_total_forms"], 40)
        self.assertEqual(n2["recommended_new_interviews"], 8)
        self.assertEqual(n2["recommended_new_self_forms"], 32)

    def test_archive_entry_has_no_individual_pair_relation(self):
        from survey_center.archive import ArchiveGateway

        archive = self.ds.table("archive_reports.csv")
        gateway = ArchiveGateway(self.ds)
        self.assertEqual(gateway.get_report("P03")["barrier_households"], "14")
        with self.assertRaises(PermissionError):
            gateway.paired_household_responses()
        self.assertEqual(
            set(archive[0]),
            {"report", "period", "published_at", "cutoff", "station", "group", "scope",
             "households", "barrier_households"},
        )
        self.assertNotIn("household", archive[0])
        self.assertNotIn("issue", archive[0])
        trends = trend_table(self.ds)
        self.assertTrue(all("P0" in r["archive_jan_report"] or r["archive_jan_report"] == "" for r in trends))


if __name__ == "__main__":
    unittest.main()
