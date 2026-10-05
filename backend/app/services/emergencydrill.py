"""应急演练业务规则：演练状态流转照常，装备清单的合格判定同步自应急救援。

装备清单里每台装备的判定不在本模块重算，而是调用 RescueService 读出的
统一结论；救援装备一旦报废或检查过期，这里看到的判定立刻同步。
"""
from __future__ import annotations

from typing import Any

from app.services.rescue import get_rescue_service
from app.store import store

MODULE = "emergencydrill"
REQUIRED_FIELDS = ["演练编号", "演练主题", "演练区域"]
STATUS_ORDER = ["待组织", "已组织", "已完成", "已复盘"]
ACTION_RULES = {"组织演练": "已组织", "完成演练": "已完成", "复盘总结": "已复盘"}
NEGATIVE_ACTIONS = []


class EmergencydrillService:
    # ---------- 读取 ----------

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("演练编号", ""))]
        serialized = [self.serialize(row) for row in rows]
        if status:
            serialized = [row for row in serialized if row.get("status") == status]
        total = len(serialized)
        start = max(page - 1, 0) * size
        return serialized[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        row = store.find(MODULE, entry_id)
        return self.serialize(row) if row is not None else None

    def serialize(self, entry: dict[str, Any]) -> dict[str, Any]:
        result = dict(entry)
        roster = self._equipment_roster(entry)
        result["演练装备清单"] = roster
        result["装备清单摘要"] = "；".join(
            f"{item['装备编号']}({item['判定']})" for item in roster
        ) or "未配备装备"
        result["装备不合格数"] = sum(1 for item in roster if not item["是否合格_bool"])
        return result

    def _equipment_roster(self, entry: dict[str, Any]) -> list[dict[str, Any]]:
        """按配备的装备 id 清单，从应急救援取统一判定结论。"""
        ids = entry.get("配备装备", [])
        roster: list[dict[str, Any]] = []
        for rescue_id in ids:
            rescue_entry = get_rescue_service().get_entry(int(rescue_id))
            if rescue_entry is None:
                continue
            roster.append({
                "装备id": rescue_entry["id"],
                "装备编号": rescue_entry.get("装备编号"),
                "装备名称": rescue_entry.get("装备名称"),
                "保有数量": rescue_entry.get("保有数量"),
                "下次检查日": rescue_entry.get("下次检查日"),
                "判定": rescue_entry["判定"],
                "是否合格": rescue_entry["是否合格"],
                "是否合格_bool": rescue_entry["判定"] == "合格可用",
                "判定依据": rescue_entry["判定依据"],
            })
        return roster

    # ---------- 写入 ----------

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        entry["配备装备"] = []
        rows.append(entry)
        return entry, []

    def assign_equipment(
        self, entry_id: int, equipment_ids: list[Any]
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"演练记录 {entry_id} 不存在或已归档"
        ids: list[int] = []
        for raw in equipment_ids:
            try:
                equipment_id = int(raw)
            except (TypeError, ValueError):
                return None, f"装备标识「{raw}」无法识别，请填写装备 id"
            if get_rescue_service().get_entry(equipment_id) is None:
                return None, f"装备 {equipment_id} 不存在或已归档"
            if equipment_id not in ids:
                ids.append(equipment_id)
        entry["配备装备"] = ids
        return self.serialize(entry), "演练装备清单已同步，判定以应急救援统一口径为准"

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
        return self.serialize(entry), f"演练记录已{action}"
