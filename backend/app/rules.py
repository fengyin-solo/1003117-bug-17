# -*- coding: utf-8 -*-
"""救援装备合格判定的唯一口径（单一事实源）。

两条业务硬规则在本模块合并成同一份判定，任何入口——救援装备列表、装备详情、
应急演练的装备清单、入井名单携带的装备——都只能调用这里的函数读取判定，
不允许各自维护一套结论：

1. 保有数量降到零（含已报废装备）即不合格；
2. 下次检查日已过期即不合格。

两条同时命中、结论冲突时，以「检查日已过期」为准；优先级写死在
:func:`judge_equipment` 里，改动口径只允许改这一个文件。
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from app.store import store

# ---------------------------------------------------------------------------
# 口径常量：判定标签、字段名、版本号都只在这里定义
# ---------------------------------------------------------------------------
QUALIFIED = "合格可用"
EXPIRED = "已过期"
ZERO_STOCK = "无保有量"
SCRAPPED = "已报废"

VERDICT_PASS = "合格"
VERDICT_FAIL = "不合格"
VERDICT_UNKNOWN = "未登记"

QUANTITY_FIELD = "保有数量"
LAST_CHECK_FIELD = "上次检查"
NEXT_CHECK_FIELD = "下次检查日"
ENTER_DATE_FIELD = "进场时间"
SCRAPPED_FIELD = "_scrapped"
HISTORY_FIELD = "判定历史"
CODE_FIELD = "装备编号"

# 当前正在执行的口径版本；旧结论只允许带着旧版本号留在判定历史里
CURRENT_RULE_VERSION = "v2-数量与检查日合并口径"
LEGACY_RULE_VERSION = "v1-历史口径（已停用）"

# 合格且下次检查日落在该窗口内时进入待检提醒；报废/归零/过期一律不进待检清单
PENDING_CHECK_WINDOW_DAYS = 30

# 装备编号在文本里可能使用的分隔符
_CODE_SPLIT_RE = re.compile(r"[,，、;；\s]+")


def parse_date(value: Any) -> date | None:
    """尽量宽松地解析 YYYY-MM-DD；解析不了返回 None，由调用方按口径处理。"""
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def parse_quantity(value: Any) -> int:
    """保有数量按非负整数解读；非法值一律视为 0（即命中归零规则）。"""
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(value, 0)
    if isinstance(value, float):
        return max(int(value), 0)
    text = str(value or "").strip()
    if not text:
        return 0
    try:
        return max(int(float(text)), 0)
    except ValueError:
        return 0


def split_equipment_codes(raw: Any) -> list[str]:
    """把「RESC-0001, RESC-0002」这类文本拆成装备编号列表，自动去重保序。"""
    if isinstance(raw, list):
        parts = [str(item).strip() for item in raw]
    else:
        parts = _CODE_SPLIT_RE.split(str(raw or ""))
    codes = [part for part in parts if part]
    seen: set[str] = set()
    result: list[str] = []
    for code in codes:
        if code not in seen:
            seen.add(code)
            result.append(code)
    return result


def judge_equipment(entry: dict[str, Any], *, today: date | None = None) -> dict[str, Any]:
    """对单台装备执行合并判定（纯函数，不落库、不改入参）。

    返回字段：
    - 判定：合格 / 不合格
    - 判定状态：合格可用 / 已过期 / 无保有量 / 已报废
    - 命中规则：按优先级排列的命中说明（可能同时命中两条）
    - 生效规则：最终采用的那一条；冲突时固定为「检查日已过期」
    - 待检：是否进入待检清单
    - 判定说明：给页面读的整句结论
    """
    today = today or date.today()
    quantity = parse_quantity(entry.get(QUANTITY_FIELD))
    next_check = parse_date(entry.get(NEXT_CHECK_FIELD))
    scrapped = bool(entry.get(SCRAPPED_FIELD))

    hit_zero = quantity <= 0
    hit_expired = next_check is not None and next_check < today

    hits: list[str] = []
    # 注意：判定优先级写死在这里——过期先于报废先于归零，冲突以过期为准。
    if hit_expired:
        hits.append("检查日已过期")
    if scrapped:
        hits.append("装备已报废")
    if hit_zero:
        hits.append("保有数量为零")

    if hit_expired:
        label = EXPIRED
        effective = "检查日已过期"
    elif scrapped:
        label = SCRAPPED
        effective = "装备已报废"
    elif hit_zero:
        label = ZERO_STOCK
        effective = "保有数量为零"
    else:
        label = QUALIFIED
        effective = ""

    verdict = VERDICT_PASS if label == QUALIFIED else VERDICT_FAIL

    if label == QUALIFIED:
        detail = "保有数量充足，检查日未过期"
    elif label == EXPIRED:
        conflict = "，与保有数量/报废口径冲突时以过期为准" if (hit_zero or scrapped) else ""
        detail = f"下次检查日 {next_check.isoformat()} 已过期{conflict}"
    elif label == SCRAPPED:
        detail = "装备已报废，保有数量为零，不再参与待检"
    else:
        detail = "保有数量已降到零，补充后方可使用"

    pending_check = (
        label == QUALIFIED
        and next_check is not None
        and today <= next_check <= today + timedelta(days=PENDING_CHECK_WINDOW_DAYS)
    )

    return {
        "判定": verdict,
        "判定状态": label,
        "命中规则": hits,
        "生效规则": effective,
        "待检": pending_check,
        "判定说明": detail,
    }


def apply_verdict(entry: dict[str, Any], *, today: date | None = None) -> dict[str, Any]:
    """把合并判定写回装备行。

    列表与详情走的是同一个函数，保证两处读到的判定永远一致；
    旧的 status / 装备状态 / pending / abnormal 字段也同步覆盖，
    避免报废后还被旧状态带进待检清单。
    """
    verdict = judge_equipment(entry, today=today)
    entry["判定结果"] = verdict["判定"]
    entry["判定状态"] = verdict["判定状态"]
    entry["命中规则"] = verdict["命中规则"]
    entry["生效规则"] = verdict["生效规则"]
    entry["判定说明"] = verdict["判定说明"]
    entry["判定口径版本"] = CURRENT_RULE_VERSION
    entry["待检"] = verdict["待检"]
    # 兼容旧字段：统一指向同一份判定，杜绝两个口径
    entry["status"] = verdict["判定状态"]
    entry["装备状态"] = verdict["判定状态"]
    entry["abnormal"] = verdict["判定"] == VERDICT_FAIL
    # 待处理 = 待检提醒 + 不合格装备，供运营概览汇总
    entry["pending"] = verdict["待检"] or entry["abnormal"]
    return entry


def equipment_catalog(*, today: date | None = None) -> dict[str, dict[str, Any]]:
    """以装备编号为键的最新台账；演练清单和入井名单都从这里取判定。"""
    catalog: dict[str, dict[str, Any]] = {}
    for row in store.rows("rescue"):
        apply_verdict(row, today=today)
        catalog[str(row.get(CODE_FIELD) or "")] = row
    return catalog


def resolve_equipment_codes(codes: Any, *, today: date | None = None) -> dict[str, Any]:
    """把一组装备编号解析成判定明细与汇总；台账里查不到的编号标记为未登记。"""
    code_list = split_equipment_codes(codes)
    catalog = equipment_catalog(today=today)
    items: list[dict[str, str]] = []
    pass_count = fail_count = unknown_count = 0
    for code in code_list:
        equipment = catalog.get(code)
        if equipment is None:
            items.append({"装备编号": code, "判定结果": VERDICT_UNKNOWN, "判定状态": "台账中未登记"})
            unknown_count += 1
        else:
            result = str(equipment.get("判定结果"))
            items.append({
                "装备编号": code,
                "判定结果": result,
                "判定状态": str(equipment.get("判定状态")),
            })
            if result == VERDICT_PASS:
                pass_count += 1
            else:
                fail_count += 1
    parts = [f"共 {len(code_list)} 台", f"合格 {pass_count} 台", f"不合格 {fail_count} 台"]
    if unknown_count:
        parts.append(f"未登记 {unknown_count} 台")
    return {
        "装备编号清单": code_list,
        "装备判定明细": items,
        "装备判定汇总": "，".join(parts),
        "全部合格": bool(code_list) and fail_count == 0 and unknown_count == 0,
    }
