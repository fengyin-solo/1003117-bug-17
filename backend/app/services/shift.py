# -*- coding: utf-8 -*-
"""入井管理业务规则：状态流转、字段校验与筛选口径。

入井人员携带设备的合格判定不在本模块自算，统一调用
``app.rules.resolve_equipment_codes``，与装备列表、演练清单同源。
"""
from __future__ import annotations

from typing import Any

from app.rules import resolve_equipment_codes, split_equipment_codes
from app.store import store

MODULE = "shift"
REQUIRED_FIELDS = ["记录编号", "入井人员", "所属班组"]
CARRIED_FIELD = "携带设备"
STATUS_ORDER = ["入井中", "已升井", "超时未升", "已联系"]
ACTION_RULES = {"登记入井": "入井中", "登记升井": "已升井", "超时联系": "已联系"}
NEGATIVE_ACTIONS = []


def _decorate(row: dict[str, Any]) -> dict[str, Any]:
    """挂接携带设备的实时判定：装备报废/过期后名单上同步变成不合格。"""
    verdict = resolve_equipment_codes(row.get(CARRIED_FIELD))
    row.update({
        "装备编号清单": verdict["装备编号清单"],
        "装备判定明细": verdict["装备判定明细"],
        "装备判定汇总": verdict["装备判定汇总"],
        "装备全部合格": verdict["全部合格"],
    })
    return row


class ShiftService:
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
            rows = [row for row in rows if keyword in str(row.get("记录编号", ""))]
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
        entry[CARRIED_FIELD] = "、".join(split_equipment_codes(values.get(CARRIED_FIELD)))
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return _decorate(dict(entry)), []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"入井记录 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于入井管理可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return _decorate(dict(entry)), f"入井记录已{action}"
