# -*- coding: utf-8 -*-
"""统一判定口径的回归测试：规则只在 app.rules 一处，这里锁住边界行为。

覆盖：
- 保有数量归零 / 检查日过期 各自与合并的判定；
- 两条同时命中冲突时以过期为准；
- 检查日倒挂拒绝、重复报废幂等；
- 演练装备清单、入井名单读到的判定与装备详情一致；
- 存量回填只执行一次，旧结论保留旧口径。
"""
from __future__ import annotations

import unittest
from datetime import date

from app.bootstrap import run_backfill
from app.rules import judge_equipment
from app.services.emergencydrill import EmergencydrillService
from app.services.rescue import (
    ACTION_INSPECT,
    ACTION_RESUPPLY,
    ACTION_SCRAP,
    RescueService,
)
from app.services.shift import ShiftService
from app.store import store

TODAY = date(2026, 10, 5)


class JudgeEquipmentTests(unittest.TestCase):
    def test_qualified_when_stock_and_date_fine(self) -> None:
        verdict = judge_equipment(
            {"保有数量": 3, "下次检查日": "2026-12-01", "_scrapped": False}, today=TODAY
        )
        self.assertEqual(verdict["判定"], "合格")
        self.assertEqual(verdict["判定状态"], "合格可用")
        self.assertEqual(verdict["命中规则"], [])

    def test_zero_quantity_fails(self) -> None:
        verdict = judge_equipment(
            {"保有数量": 0, "下次检查日": "2026-12-01", "_scrapped": False}, today=TODAY
        )
        self.assertEqual(verdict["判定"], "不合格")
        self.assertEqual(verdict["判定状态"], "无保有量")
        self.assertEqual(verdict["生效规则"], "保有数量为零")

    def test_expired_date_fails(self) -> None:
        verdict = judge_equipment(
            {"保有数量": 5, "下次检查日": "2026-10-04", "_scrapped": False}, today=TODAY
        )
        self.assertEqual(verdict["判定状态"], "已过期")
        # 检查日当天不算过期
        on_day = judge_equipment(
            {"保有数量": 5, "下次检查日": "2026-10-05", "_scrapped": False}, today=TODAY
        )
        self.assertEqual(on_day["判定状态"], "合格可用")

    def test_conflict_expired_wins_over_scrap_and_zero(self) -> None:
        verdict = judge_equipment(
            {"保有数量": 0, "下次检查日": "2026-01-01", "_scrapped": True}, today=TODAY
        )
        self.assertEqual(verdict["判定状态"], "已过期")
        self.assertEqual(verdict["生效规则"], "检查日已过期")
        self.assertEqual(
            verdict["命中规则"], ["检查日已过期", "装备已报废", "保有数量为零"]
        )

    def test_scrapped_without_expiry(self) -> None:
        verdict = judge_equipment(
            {"保有数量": 0, "下次检查日": "2027-01-01", "_scrapped": True}, today=TODAY
        )
        self.assertEqual(verdict["判定状态"], "已报废")
        self.assertTrue(verdict["待检"] is False)

    def test_pending_check_window(self) -> None:
        soon = judge_equipment(
            {"保有数量": 1, "下次检查日": "2026-10-20", "_scrapped": False}, today=TODAY
        )
        self.assertTrue(soon["待检"])
        far = judge_equipment(
            {"保有数量": 1, "下次检查日": "2026-12-01", "_scrapped": False}, today=TODAY
        )
        self.assertFalse(far["待检"])


class RescueServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        store.reset()
        run_backfill()
        self.service = RescueService()

    def test_inspect_date_earlier_than_last_is_rejected(self) -> None:
        # RESC-0001 上次检查为 2026-03-10
        entry, message = self.service.run_action(
            1, ACTION_INSPECT, {"上次检查": "2026-02-28", "下次检查日": "2027-02-28"}
        )
        self.assertIsNone(entry)
        self.assertIn("不允许倒挂", message)

    def test_next_date_earlier_than_inspect_is_rejected(self) -> None:
        entry, message = self.service.run_action(
            1, ACTION_INSPECT, {"上次检查": "2026-09-01", "下次检查日": "2026-08-31"}
        )
        self.assertIsNone(entry)
        self.assertIn("不允许倒挂", message)

    def test_duplicate_scrap_applies_once(self) -> None:
        first = self.service.run_action(4, ACTION_SCRAP)
        second = self.service.run_action(4, ACTION_SCRAP)
        third = self.service.run_action(4, ACTION_SCRAP)
        self.assertTrue(first[0] is not None)
        self.assertIn("已报废", first[1])
        self.assertIn("重复申请不再生效", second[1])
        self.assertIn("重复申请不再生效", third[1])
        history = self.service.get_entry(4)["判定历史"]
        self.assertEqual(len(history), 2)  # 一条回填 + 一次报废
        self.assertEqual(history[-1]["场景"], ACTION_SCRAP)

    def test_scrap_zeroes_quantity_and_removes_from_pending_check(self) -> None:
        self.service.run_action(2, ACTION_SCRAP)
        entry = self.service.get_entry(2)
        self.assertEqual(entry["保有数量"], 0)
        self.assertFalse(entry["待检"])
        self.assertEqual(entry["abnormal"], True)

    def test_resupply_revives_equipment(self) -> None:
        self.service.run_action(4, ACTION_SCRAP)
        entry, _ = self.service.run_action(4, ACTION_RESUPPLY, {"保有数量": 6})
        self.assertEqual(entry["判定状态"], "合格可用")
        self.assertEqual(entry["保有数量"], 6)
        self.assertFalse(entry["_scrapped"])

    def test_resupply_zero_rejected(self) -> None:
        entry, message = self.service.run_action(4, ACTION_RESUPPLY, {"保有数量": 0})
        self.assertIsNone(entry)
        self.assertIn("必须大于零", message)

    def test_list_and_detail_share_same_verdict(self) -> None:
        listed = {row["id"]: row for row in self.service.list_entries()[0]}
        for entry_id, row in listed.items():
            detail = self.service.get_entry(entry_id)
            for field in ("判定结果", "判定状态", "命中规则", "生效规则", "判定说明"):
                self.assertEqual(row[field], detail[field], f"字段 {field} 列表详情不一致")

    def test_legacy_history_preserved_on_backfill(self) -> None:
        # 存量装备第一条历史必须是旧口径存档
        entry = self.service.get_entry(3)
        first = entry["判定历史"][0]
        self.assertIn("v1", first["口径版本"])
        self.assertEqual(first["判定状态"], "已报废")
        # 再跑一次回填不追加
        run_backfill()
        self.assertEqual(len(self.service.get_entry(3)["判定历史"]), 1)

    def test_expired_over_scrap_after_action(self) -> None:
        # 报废一台检查日本就过期的装备（RESC-0005），结论仍以过期为准
        entry, _ = self.service.run_action(5, ACTION_SCRAP)
        self.assertEqual(entry["判定状态"], "已过期")
        self.assertEqual(entry["生效规则"], "检查日已过期")


class SyncVerdictTests(unittest.TestCase):
    def setUp(self) -> None:
        store.reset()
        run_backfill()
        self.rescue = RescueService()
        self.drill = EmergencydrillService()
        self.shift = ShiftService()

    def test_drill_and_shift_read_same_verdict_as_detail(self) -> None:
        self.rescue.run_action(1, ACTION_SCRAP)
        detail = self.rescue.get_entry(1)

        drill_rows = {code: item
                      for row in self.drill.list_entries()[0]
                      for item in row["装备判定明细"]
                      for code in [item["装备编号"]]}
        self.assertEqual(drill_rows["RESC-0001"]["判定状态"], detail["判定状态"])

        shift_rows = {code: item
                      for row in self.shift.list_entries()[0]
                      for item in row["装备判定明细"]
                      for code in [item["装备编号"]]}
        self.assertEqual(shift_rows["RESC-0001"]["判定状态"], detail["判定状态"])

    def test_drill_summary_flags_unqualified(self) -> None:
        rows = {row["演练编号"]: row for row in self.drill.list_entries()[0]}
        # EMER-0001：RESC-0001/0002 初始均合格
        self.assertTrue(rows["EMER-0001"]["装备全部合格"])
        # EMER-0002：RESC-0005 已过期
        self.assertFalse(rows["EMER-0002"]["装备全部合格"])
        self.assertIn("不合格 1 台", rows["EMER-0002"]["装备判定汇总"])

    def test_unknown_equipment_marked(self) -> None:
        entry, _ = self.drill.create_entry({
            "演练编号": "EMER-0099",
            "演练主题": "测试",
            "演练区域": "测试面",
            "装备清单": "RESC-0001,RESC-X",
        })
        codes = {item["装备编号"]: item for item in entry["装备判定明细"]}
        self.assertEqual(codes["RESC-X"]["判定结果"], "未登记")
        self.assertFalse(entry["装备全部合格"])


if __name__ == "__main__":
    unittest.main()
