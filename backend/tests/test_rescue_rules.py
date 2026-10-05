"""统一判定口径与同步行为的回归测试（仅用标准库：python3 -m unittest discover）。"""
from __future__ import annotations

import unittest
from datetime import date

from app.services import rescue_rules
from app.services.emergencydrill import EmergencydrillService
from app.services.rescue import reset_rescue_service
from app.services.shift import ShiftService
from app.store import store


class RuleMatrixTest(unittest.TestCase):
    """两条判定合成一份，冲突时以过期为准。"""

    AS_OF = date(2026, 10, 5)

    def verdict(self, entry):
        return rescue_rules.evaluate(entry, as_of=self.AS_OF)

    def test_qualified_when_in_stock_and_not_expired(self):
        v = self.verdict({"保有数量": 5, "下次检查日": "2026-11-01"})
        self.assertEqual(v["judgement"], rescue_rules.JUDGEMENT_QUALIFIED)
        self.assertTrue(v["qualified"])

    def test_zero_stock_is_scrapped(self):
        v = self.verdict({"保有数量": 0, "下次检查日": "2026-11-01"})
        self.assertEqual(v["judgement"], rescue_rules.JUDGEMENT_SCRAPPED)
        self.assertFalse(v["qualified"])
        self.assertIn(rescue_rules.REASON_ZERO_STOCK, v["reasons"])

    def test_expired_date_is_expired(self):
        v = self.verdict({"保有数量": 5, "下次检查日": "2026-10-04"})
        self.assertEqual(v["judgement"], rescue_rules.JUDGEMENT_EXPIRED)
        self.assertFalse(v["qualified"])

    def test_both_hit_expired_takes_precedence(self):
        v = self.verdict({"保有数量": 0, "下次检查日": "2026-10-04"})
        self.assertEqual(v["judgement"], rescue_rules.JUDGEMENT_EXPIRED)
        self.assertEqual(v["matched"], [rescue_rules.JUDGEMENT_SCRAPPED, rescue_rules.JUDGEMENT_EXPIRED])

    def test_check_due_today_is_not_expired(self):
        v = self.verdict({"保有数量": 1, "下次检查日": "2026-10-05"})
        self.assertEqual(v["judgement"], rescue_rules.JUDGEMENT_QUALIFIED)

    def test_unparseable_values_do_not_false_trigger(self):
        v = self.verdict({"保有数量": "样例文本", "下次检查日": "样例文本"})
        self.assertEqual(v["judgement"], rescue_rules.JUDGEMENT_QUALIFIED)

    def test_inspection_date_order(self):
        self.assertTrue(rescue_rules.inspection_dates_valid("2026-10-01", "2026-10-01"))
        self.assertFalse(rescue_rules.inspection_dates_valid("2026-10-02", "2026-10-01"))


class RescueServiceTest(unittest.TestCase):
    def setUp(self):
        store.reset()
        self.service = reset_rescue_service()

    def test_legacy_backfill_by_entry_time(self):
        for entry_id in (1, 2, 3):
            entry = self.service.get_entry(entry_id)
            self.assertTrue(entry["进场时间"])
            self.assertGreaterEqual(entry["下次检查日"], entry["上次检查"])
            legacy = entry["判定历史"][0]
            self.assertTrue(legacy["口径版本"].startswith("旧口径"))
            self.assertEqual(legacy["结论"], entry_id == 2 and "需补充" or ("已过期" if entry_id == 3 else "合格可用"))

    def test_seed_verdicts_and_conflict_priority(self):
        self.assertEqual(self.service.get_entry(4)["判定"], rescue_rules.JUDGEMENT_QUALIFIED)
        self.assertEqual(self.service.get_entry(5)["判定"], rescue_rules.JUDGEMENT_EXPIRED)
        self.assertEqual(self.service.get_entry(6)["判定"], rescue_rules.JUDGEMENT_SCRAPPED)
        conflict = self.service.get_entry(7)
        self.assertEqual(conflict["判定"], rescue_rules.JUDGEMENT_EXPIRED)
        self.assertEqual(conflict["命中判定"], [rescue_rules.JUDGEMENT_SCRAPPED, rescue_rules.JUDGEMENT_EXPIRED])

    def test_list_and_detail_share_one_verdict(self):
        items, _ = self.service.list_entries(page=1, size=100)
        for row in items:
            self.assertEqual(self.service.get_entry(row["id"])["判定"], row["判定"])

    def test_status_filter_uses_derived_verdict(self):
        items, total = self.service.list_entries(status=rescue_rules.JUDGEMENT_SCRAPPED, page=1, size=100)
        self.assertTrue(items)
        self.assertTrue(all(row["判定"] == rescue_rules.JUDGEMENT_SCRAPPED for row in items))
        self.assertEqual(total, len(items))

    def test_scrap_is_idempotent(self):
        # id=5 在过期用例外不参与同步，报废后检查日仍过期，结论为已过期
        entry, _ = self.service.run_action(5, "申请报废")
        self.assertEqual(entry["保有数量"], 0)
        self.assertEqual(entry["判定"], rescue_rules.JUDGEMENT_EXPIRED)
        history_len = len(entry["判定历史"])
        again, message = self.service.run_action(5, "申请报废")
        self.assertIn("已报废", message)
        self.assertEqual(len(again["判定历史"]), history_len)
        self.assertEqual(again["保有数量"], 0)

    def test_inspection_earlier_than_last_is_rejected(self):
        entry, message = self.service.record_inspection(4, "2026-10-01", "2026-09-01")
        self.assertIsNone(entry)
        self.assertIn("不能早于", message)

    def test_inspection_refreshes_verdict(self):
        entry, message = self.service.record_inspection(4, "2026-10-01", "2026-12-01")
        self.assertIsNotNone(entry)
        self.assertEqual(entry["判定"], rescue_rules.JUDGEMENT_QUALIFIED)

    def test_create_rejects_inverted_dates(self):
        entry, message = self.service.create_entry({
            "装备编号": "RESC-T1", "装备名称": "x", "装备类别": "y",
            "上次检查": "2026-10-01", "下次检查日": "2026-09-01",
        })
        self.assertIsNone(entry)
        self.assertIn("不能早于", message)

    def test_history_is_append_only(self):
        before = len(self.service.get_entry(6)["判定历史"])
        self.service.record_inspection(6, "2026-10-01", "2026-12-01")
        after = self.service.get_entry(6)["判定历史"]
        self.assertGreaterEqual(len(after), before)
        self.assertTrue(all(item["结论"] for item in after))


class SyncTest(unittest.TestCase):
    def setUp(self):
        store.reset()
        self.rescue = reset_rescue_service()
        self.drill = EmergencydrillService()
        self.shift = ShiftService()

    def test_drill_roster_tracks_unified_verdict(self):
        roster = {item["装备id"]: item["判定"] for item in self.drill.get_entry(1)["演练装备清单"]}
        self.assertEqual(roster[4], rescue_rules.JUDGEMENT_QUALIFIED)
        self.assertEqual(roster[6], rescue_rules.JUDGEMENT_SCRAPPED)

    def test_scrap_propagates_to_drill_and_shift(self):
        # 入井1 携带 4、5（5 已过期）；把 4 报废后，演练和入井两处同步为报废/不合格
        self.rescue.run_action(4, "申请报废")
        roster = {item["装备id"]: item for item in self.drill.get_entry(1)["演练装备清单"]}
        self.assertEqual(roster[4]["判定"], rescue_rules.JUDGEMENT_SCRAPPED)
        self.assertFalse(roster[4]["是否合格_bool"])
        carried = {item["装备id"]: item["判定"] for item in self.shift.get_entry(1)["携带装备判定"]}
        self.assertEqual(carried[4], rescue_rules.JUDGEMENT_SCRAPPED)
        self.assertEqual(self.shift.get_entry(1)["携带不合格装备数"], 2)

    def test_assign_unknown_equipment_rejected(self):
        entry, message = self.drill.assign_equipment(1, [9999])
        self.assertIsNone(entry)
        self.assertIn("不存在", message)
        entry, message = self.shift.assign_equipment(1, [9999])
        self.assertIsNone(entry)
        self.assertIn("不存在", message)


if __name__ == "__main__":
    unittest.main()
