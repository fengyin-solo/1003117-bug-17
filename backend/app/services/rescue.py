"""应急救援业务规则：装备判定只调用 rescue_rules.evaluate，不在别处下结论。

判定结果实时派生，列表、详情、应急演练装备清单、入井名单读到的都是同一份。
存量装备按进场时间在模块加载时回填一次；历史判定只追加不改写。
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from app.services import rescue_rules
from app.store import store

MODULE = "rescue"
REQUIRED_FIELDS = ["装备编号", "装备名称", "装备类别"]

# 状态流转动作（判定结论由规则决定，这里只维护动作本身是否合法）。
ACTION_RULES = ["登记不足", "补充装备", "申请报废"]

# 存量回填基准：没有进场时间的老记录，按 id 摊到这个基准前后的日期上。
BACKFILL_BASE_DATE = date(2026, 8, 1)


class RescueService:
    def __init__(self) -> None:
        self.backfill_legacy()

    # ---------- 读取：列表与详情都经 serialize，结论天然一致 ----------

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
            rows = [row for row in rows if keyword in str(row.get("装备编号", ""))]
        serialized = [self.serialize(row) for row in rows]
        if status:
            serialized = [row for row in serialized if row["判定"] == status]
        total = len(serialized)
        start = max(page - 1, 0) * size
        return serialized[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        row = store.find(MODULE, entry_id)
        return self.serialize(row) if row is not None else None

    def all_serialized(self) -> list[dict[str, Any]]:
        return [self.serialize(row) for row in store.rows(MODULE)]

    def serialize(self, entry: dict[str, Any]) -> dict[str, Any]:
        """组装对外结构：原始字段 + 统一判定结果，任何入口都不绕过它。"""
        result = dict(entry)
        verdict = rescue_rules.evaluate(entry)
        result["判定"] = verdict["judgement"]
        result["是否合格"] = "合格" if verdict["qualified"] else "不合格"
        result["判定依据"] = "；".join(verdict["reasons"])
        result["命中判定"] = verdict["matched"]
        result["判定口径"] = verdict["rule_version"]
        result["判定基准日"] = verdict["as_of"]
        result["待检"] = verdict["judgement"] not in (
            rescue_rules.JUDGEMENT_EXPIRED,
            rescue_rules.JUDGEMENT_SCRAPPED,
        )
        result["装备状态"] = verdict["judgement"]
        result["pending"] = result["待检"]
        result["abnormal"] = not verdict["qualified"]
        return result

    def stats(self) -> dict[str, int]:
        rows = self.all_serialized()
        return {
            "合格": sum(1 for row in rows if row["判定"] == rescue_rules.JUDGEMENT_QUALIFIED),
            "已过期": sum(1 for row in rows if row["判定"] == rescue_rules.JUDGEMENT_EXPIRED),
            "已报废": sum(1 for row in rows if row["判定"] == rescue_rules.JUDGEMENT_SCRAPPED),
            "待检": sum(1 for row in rows if row["待检"]),
        }

    # ---------- 写入 ----------

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, f"缺少必填字段：{'、'.join(missing)}"

        last_check = str(values.get("上次检查") or "").strip()
        next_check = str(values.get("下次检查日") or "").strip()
        if last_check and next_check and not rescue_rules.inspection_dates_valid(last_check, next_check):
            return None, "下次检查日不能早于上次检查，登记已退回"

        rows = store.rows(MODULE)
        entry: dict[str, Any] = {
            "id": max((int(row.get("id", 0)) for row in rows), default=0) + 1,
        }
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["存放地点"] = str(values.get("存放地点") or "").strip()
        entry["保有数量"] = rescue_rules.parse_quantity(values.get("保有数量")) or 1
        entry["上次检查"] = last_check or date.today().isoformat()
        entry["下次检查日"] = next_check
        entry["进场时间"] = date.today().isoformat()
        entry["已报废"] = False
        entry["判定历史"] = []
        self._append_history(entry, "登记装备")
        rows.append(entry)
        return self.serialize(entry), ""

    def record_inspection(
        self, entry_id: int, last_check: str, next_check: str
    ) -> tuple[dict[str, Any] | None, str]:
        """保存检查记录：不允许下次检查日早于上次检查。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"救援装备 {entry_id} 不存在或已归档"
        last_check = (last_check or "").strip()
        next_check = (next_check or "").strip()
        if not last_check or not next_check:
            return None, "上次检查和下次检查日都必须填写"
        if not rescue_rules.parse_date(last_check) or not rescue_rules.parse_date(next_check):
            return None, "检查日期需写成 YYYY-MM-DD 形式"
        if not rescue_rules.inspection_dates_valid(last_check, next_check):
            return None, "下次检查日不能早于上次检查，检查记录未保存"
        entry["上次检查"] = last_check
        entry["下次检查日"] = next_check
        self._append_history(entry, "登记检查")
        return self.serialize(entry), "检查记录已保存，判定已按统一口径更新"

    def run_action(self, entry_id: int, action: str, extras: dict[str, Any] | None = None) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"救援装备 {entry_id} 不存在或已归档"
        extras = extras or {}

        if action == "申请报废":
            # 重复提交报废只生效一次：再点不重复扣数量、不重复记历史。
            if rescue_rules.parse_quantity(entry.get("保有数量")) == 0 or entry.get("已报废"):
                return self.serialize(entry), "该装备已报废，重复提交不再重复生效"
            entry["保有数量"] = 0
            entry["已报废"] = True
            self._append_history(entry, action)
            return self.serialize(entry), "救援装备已报废，保有数量归零"

        if action == "补充装备":
            add = rescue_rules.parse_quantity(extras.get("补充数量"))
            if add is None:
                return None, "补充数量需为非负整数"
            current = rescue_rules.parse_quantity(entry.get("保有数量")) or 0
            entry["保有数量"] = current + add
            entry["已报废"] = False
            self._append_history(entry, action)
            return self.serialize(entry), f"已补充 {add} 台，保有数量现为 {entry['保有数量']}"

        if action == "登记不足":
            shortage = rescue_rules.parse_quantity(extras.get("缺口数量"))
            if shortage is None:
                return None, "缺口数量需为非负整数"
            entry["缺口数量"] = shortage
            self._append_history(entry, action)
            # 旧口径下这会变成「需补充」；新口径仍按保有数量与检查日统一判定。
            return self.serialize(entry), "缺口已登记，判定以统一口径为准"

        return None, f"动作「{action}」不属于应急救援可执行范围"

    # ---------- 判定历史：只追加，旧结论按当时口径保留 ----------

    def _append_history(self, entry: dict[str, Any], trigger: str) -> None:
        history = entry.setdefault("判定历史", [])
        verdict = rescue_rules.evaluate(entry)
        history.append({
            "时间": date.today().isoformat(),
            "触发": trigger,
            "结论": verdict["judgement"],
            "依据": "；".join(verdict["reasons"]),
            "口径版本": verdict["rule_version"],
        })

    # ---------- 存量装备按进场时间回填（只跑一次） ----------

    def backfill_legacy(self) -> None:
        """给老记录补进场时间、可解析的检查日期与旧口径历史结论。

        - 已经有进场时间的（新口径记录）原样不动；
        - 老记录的进场时间按 id 摊到基准日附近，上次检查取进场后 10 天、
          下次检查日取进场后 45 天，保证「下次检查日不早于上次检查」；
        - 旧结论按旧口径原样保留进判定历史，不改写。
        """
        for entry in store.rows(MODULE):
            history = entry.setdefault("判定历史", [])
            if entry.get("回填已完成"):
                continue
            if any(item.get("口径版本") == rescue_rules.LEGACY_RULE_VERSION for item in history):
                entry["回填已完成"] = True
                continue
            if entry.get("进场时间"):
                # 新口径存量行：只补一次进场快照，随后不再重复追加。
                if not history:
                    verdict = rescue_rules.evaluate(entry)
                    history.append({
                        "时间": str(entry["进场时间"]),
                        "触发": "进场登记（存量）",
                        "结论": verdict["judgement"],
                        "依据": "；".join(verdict["reasons"]),
                        "口径版本": verdict["rule_version"],
                    })
                entry["回填已完成"] = True
                continue

            entry_id = int(entry.get("id", 0))
            entered_at = BACKFILL_BASE_DATE + timedelta(days=(entry_id - 1) * 7)
            entry["进场时间"] = entered_at.isoformat()

            quantity = rescue_rules.parse_quantity(entry.get("保有数量"))
            if quantity is None:
                quantity = entry_id * 10
                entry["保有数量"] = quantity

            last_date = entered_at + timedelta(days=10)
            # 下次检查日按进场批次错开：老批次已到检、近批次未到检，
            # 回填后能同时看到过期与待检；偏移只取决于进场时间。
            next_days_after_entry = {1: 45, 2: 70, 3: 80}.get(entry_id, 45)
            next_date = entered_at + timedelta(days=next_days_after_entry)
            if not rescue_rules.parse_date(entry.get("上次检查")):
                entry["上次检查"] = last_date.isoformat()
            if not rescue_rules.parse_date(entry.get("下次检查日")):
                entry["下次检查日"] = next_date.isoformat()

            legacy_status = str(entry.get("status") or "").strip() or rescue_rules.JUDGEMENT_QUALIFIED
            history.append({
                "时间": entered_at.isoformat(),
                "触发": "存量回填（旧口径结论留存）",
                "结论": legacy_status,
                "依据": "按当时口径判定，仅作历史保留",
                "口径版本": rescue_rules.LEGACY_RULE_VERSION,
            })
            entry["回填已完成"] = True


# 单一服务实例：演练、入井等下游模块都通过 get_rescue_service 读同一份判定，
# 避免多处各自实例化导致回填重复、结论分叉。
_service: RescueService | None = None


def get_rescue_service() -> RescueService:
    global _service
    if _service is None:
        _service = RescueService()
    return _service


def reset_rescue_service() -> RescueService:
    """重建仓库后（测试隔离）重新绑定服务实例。"""
    global _service
    _service = RescueService()
    return _service
