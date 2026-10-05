# -*- coding: utf-8 -*-
"""应急救援业务规则：合格判定、状态流转与字段校验。

合格/不合格的口径不在本文件内自说自话，全部委托给 :mod:`app.rules`；
本文件只负责动作流转（登记检查、补充装备、申请报废）和写入约束。
"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.rules import (
    CURRENT_RULE_VERSION,
    ENTER_DATE_FIELD,
    EXPIRED,
    HISTORY_FIELD,
    LAST_CHECK_FIELD,
    NEXT_CHECK_FIELD,
    QUALIFIED,
    QUANTITY_FIELD,
    SCRAPPED,
    SCRAPPED_FIELD,
    VERDICT_PASS,
    ZERO_STOCK,
    apply_verdict,
    judge_equipment,
    parse_date,
    parse_quantity,
)
from app.store import store

MODULE = "rescue"
REQUIRED_FIELDS = ["装备编号", "装备名称", "装备类别"]
OPTIONAL_FIELDS = ["存放地点", QUANTITY_FIELD, LAST_CHECK_FIELD, NEXT_CHECK_FIELD, ENTER_DATE_FIELD]
# 只保留这三个写入口；判定口径统一在 app.rules 里，入口不允许各自下结论
ACTION_INSPECT = "登记检查"
ACTION_RESUPPLY = "补充装备"
ACTION_SCRAP = "申请报废"
SUPPORTED_ACTIONS = [ACTION_INSPECT, ACTION_RESUPPLY, ACTION_SCRAP]


class RescueService:
    # ------------------------------------------------------------------ 读
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = [apply_verdict(dict(row)) for row in store.rows(MODULE)]
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("装备编号", ""))]
        if status:
            # 状态过滤也按统一判定后的状态来，不能按历史 status 各算各的
            rows = [row for row in rows if row.get("判定状态") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None
        # 与列表同一个出口，详情判定不可能和列表打架
        return apply_verdict(dict(entry))

    def stats(self, *, today: date | None = None) -> dict[str, int]:
        counts = {"合格装备": 0, "无保有量": 0, "过期装备": 0, "已报废": 0, "待检提醒": 0}
        for row in store.rows(MODULE):
            verdict = judge_equipment(row, today=today)
            label = verdict["判定状态"]
            if label == QUALIFIED:
                counts["合格装备"] += 1
            elif label == SCRAPPED:
                counts["已报废"] += 1
            elif label == ZERO_STOCK:
                counts["无保有量"] += 1
            elif label == EXPIRED:
                counts["过期装备"] += 1
            if verdict["待检"]:
                counts["待检提醒"] += 1
        return counts

    # ------------------------------------------------------------------ 写
    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        code = str(values.get("装备编号")).strip()
        if any(str(row.get("装备编号")) == code for row in rows):
            return None, [f"装备编号 {code} 已存在，不能重复登记"]

        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: str(values.get(field) or "").strip() for field in REQUIRED_FIELDS})
        entry["存放地点"] = str(values.get("存放地点") or "").strip()
        entry[QUANTITY_FIELD] = parse_quantity(values.get(QUANTITY_FIELD, 1))
        entry[LAST_CHECK_FIELD] = str(values.get(LAST_CHECK_FIELD) or "")
        entry[NEXT_CHECK_FIELD] = str(values.get(NEXT_CHECK_FIELD) or "")
        enter_date = parse_date(values.get(ENTER_DATE_FIELD)) or date.today()
        entry[ENTER_DATE_FIELD] = enter_date.isoformat()
        entry[SCRAPPED_FIELD] = False
        entry[HISTORY_FIELD] = []

        apply_verdict(entry)
        self._append_history(entry, "登记入场")
        rows.append(entry)
        return dict(entry), []

    def run_action(
        self,
        entry_id: int,
        action: str,
        values: dict[str, Any] | None = None,
        *,
        today: date | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"救援装备 {entry_id} 不存在或已归档"
        if action not in SUPPORTED_ACTIONS:
            return None, f"动作「{action}」不属于应急救援可执行范围（仅支持：{'、'.join(SUPPORTED_ACTIONS)}）"

        today = today or date.today()
        if action == ACTION_INSPECT:
            return self._inspect(entry, values or {}, today=today)
        if action == ACTION_RESUPPLY:
            return self._resupply(entry, values or {}, today=today)
        return self._scrap(entry, today=today)

    # ------------------------------------------------------------ 动作实现
    def _inspect(
        self, entry: dict[str, Any], values: dict[str, Any], *, today: date
    ) -> tuple[dict[str, Any] | None, str]:
        if entry.get(SCRAPPED_FIELD):
            return None, "装备已报废，不能再登记检查；如需重新启用请先补充装备"

        last_check = parse_date(values.get(LAST_CHECK_FIELD))
        if last_check is None:
            return None, f"「{LAST_CHECK_FIELD}」必须是 YYYY-MM-DD 格式的有效日期"
        previous = parse_date(entry.get(LAST_CHECK_FIELD))
        # 硬约束：不允许保存检查日早于上次检查的记录
        if previous is not None and last_check < previous:
            return None, (
                f"本次检查日 {last_check.isoformat()} 早于上次检查 {previous.isoformat()}，"
                "检查记录不允许倒挂"
            )

        next_check = parse_date(values.get(NEXT_CHECK_FIELD))
        if next_check is None:
            return None, f"「{NEXT_CHECK_FIELD}」必须是 YYYY-MM-DD 格式的有效日期"
        if next_check < last_check:
            return None, (
                f"下次检查日 {next_check.isoformat()} 早于本次检查日 {last_check.isoformat()}，"
                "检查记录不允许倒挂"
            )

        entry[LAST_CHECK_FIELD] = last_check.isoformat()
        entry[NEXT_CHECK_FIELD] = next_check.isoformat()
        apply_verdict(entry, today=today)
        self._append_history(entry, ACTION_INSPECT)
        return dict(entry), f"已登记检查（{last_check.isoformat()}），判定：{entry['判定状态']}"

    def _resupply(
        self, entry: dict[str, Any], values: dict[str, Any], *, today: date
    ) -> tuple[dict[str, Any] | None, str]:
        if QUANTITY_FIELD not in values:
            return None, f"补充装备必须提交「{QUANTITY_FIELD}」"
        quantity = parse_quantity(values.get(QUANTITY_FIELD))
        if quantity <= 0:
            return None, "补充后的保有数量必须大于零，归零只能通过申请报废处理"

        entry[QUANTITY_FIELD] = quantity
        entry[SCRAPPED_FIELD] = False
        apply_verdict(entry, today=today)
        self._append_history(entry, ACTION_RESUPPLY)
        return dict(entry), f"保有数量已更新为 {quantity}，判定：{entry['判定状态']}"

    def _scrap(
        self, entry: dict[str, Any], *, today: date
    ) -> tuple[dict[str, Any] | None, str]:
        # 重复提交报废只生效一次：已报废直接幂等返回，不再产生新结论
        if entry.get(SCRAPPED_FIELD):
            apply_verdict(entry, today=today)
            return dict(entry), "该装备此前已报废，重复申请不再生效"

        entry[SCRAPPED_FIELD] = True
        entry[QUANTITY_FIELD] = 0
        apply_verdict(entry, today=today)
        self._append_history(entry, ACTION_SCRAP)
        return dict(entry), f"已报废并清零保有数量，判定：{entry['判定状态']}"

    def _append_history(self, entry: dict[str, Any], scene: str) -> None:
        """追加一条当时口径下的判定结论；历史只追加不改写。"""
        history = entry.setdefault(HISTORY_FIELD, [])
        verdict = {
            "判定": entry.get("判定结果", VERDICT_PASS),
            "判定状态": entry.get("判定状态", QUALIFIED),
            "命中规则": list(entry.get("命中规则", [])),
            "生效规则": entry.get("生效规则", ""),
        }
        history.append({
            "时间": date.today().isoformat(),
            "场景": scene,
            "口径版本": CURRENT_RULE_VERSION,
            **verdict,
        })
