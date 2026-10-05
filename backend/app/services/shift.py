"""入井管理业务规则：入井记录状态流转照常，携带装备的合格判定同步自应急救援。

入井名单上每台携带装备显示的判定都调用应急救援的统一结论，不单独下判断。
"""
from __future__ import annotations

from typing import Any

from app.services.rescue import get_rescue_service
from app.store import store

MODULE = "shift"
REQUIRED_FIELDS = ["记录编号", "入井人员", "所属班组"]
STATUS_ORDER = ["入井中", "已升井", "超时未升", "已联系"]
ACTION_RULES = {"登记入井": "入井中", "登记升井": "已升井", "超时联系": "已联系"}
NEGATIVE_ACTIONS = []


class ShiftService:
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
            rows = [row for row in rows if keyword in str(row.get("记录编号", ""))]
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
        carried = self._carried_equipment(entry)
        result["携带装备判定"] = carried
        result["携带装备判定摘要"] = "；".join(
            f"{item['装备编号']}({item['判定']})" for item in carried
        ) or "未登记携带装备"
        result["携带不合格装备数"] = sum(1 for item in carried if not item["是否合格_bool"])
        return result

    def _carried_equipment(self, entry: dict[str, Any]) -> list[dict[str, Any]]:
        ids = entry.get("携带装备清单", [])
        carried: list[dict[str, Any]] = []
        for rescue_id in ids:
            rescue_entry = get_rescue_service().get_entry(int(rescue_id))
            if rescue_entry is None:
                continue
            carried.append({
                "装备id": rescue_entry["id"],
                "装备编号": rescue_entry.get("装备编号"),
                "装备名称": rescue_entry.get("装备名称"),
                "判定": rescue_entry["判定"],
                "是否合格": rescue_entry["是否合格"],
                "是否合格_bool": rescue_entry["判定"] == "合格可用",
                "判定依据": rescue_entry["判定依据"],
            })
        return carried

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
        entry["携带装备清单"] = []
        rows.append(entry)
        return entry, []

    def assign_equipment(
        self, entry_id: int, equipment_ids: list[Any]
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"入井记录 {entry_id} 不存在或已归档"
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
        entry["携带装备清单"] = ids
        return self.serialize(entry), "入井携带装备已登记，判定以应急救援统一口径为准"

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
        return self.serialize(entry), f"入井记录已{action}"
