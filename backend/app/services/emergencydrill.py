# -*- coding: utf-8 -*-
"""应急演练业务规则：状态流转、字段校验与筛选口径。

演练携带的装备清单不在本模块自行判断合格与否，统一调用
``app.rules.resolve_equipment_codes`` 读取救援装备台账的合并判定。
"""
from __future__ import annotations

from typing import Any

from app.rules import split_equipment_codes
from app.rules import resolve_equipment_codes
from app.store import store

MODULE = "emergencydrill"
REQUIRED_FIELDS = ["演练编号", "演练主题", "演练区域"]
EQUIPMENT_FIELD = "装备清单"
STATUS_ORDER = ["待组织", "已组织", "已完成", "已复盘"]
ACTION_RULES = {"组织演练": "已组织", "完成演练": "已完成", "复盘总结": "已复盘"}
NEGATIVE_ACTIONS = []


def _decorate(row: dict[str, Any]) -> dict[str, Any]:
    """挂接装备清单的实时判定：与装备列表/详情同源，结论不可能不一致。"""
    verdict = resolve_equipment_codes(row.get(EQUIPMENT_FIELD))
    row.update({
        "装备编号清单": verdict["装备编号清单"],
        "装备判定明细": verdict["装备判定明细"],
        "装备判定汇总": verdict["装备判定汇总"],
        "装备全部合格": verdict["全部合格"],
    })
    return row


class EmergencydrillService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = [_decorate(dict(row)) for row in store.rows(MODULE)]
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("演练编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        return _decorate(dict(entry)) if entry is not None else None

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry[EQUIPMENT_FIELD] = "、".join(split_equipment_codes(values.get(EQUIPMENT_FIELD)))
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return _decorate(dict(entry)), []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"演练记录 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于应急演练可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return _decorate(dict(entry)), f"演练记录已{action}"
