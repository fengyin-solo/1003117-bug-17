# -*- coding: utf-8 -*-
"""一次性数据回填：把骨架示例数据升级到「合并判定」口径。

两条迁移纪律：

1. 旧结论按当时的口径保留——存量装备先按进场时间补一条带旧版本号的
   判定历史（v1），之后的任何新结论才挂当前版本（v2），历史只追加不改写；
2. 幂等——迁移标记写在行内，重复启动不会重复追加，也不会覆盖已有值。
"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.rules import (
    ENTER_DATE_FIELD,
    HISTORY_FIELD,
    LAST_CHECK_FIELD,
    LEGACY_RULE_VERSION,
    NEXT_CHECK_FIELD,
    QUANTITY_FIELD,
    SCRAPPED_FIELD,
    apply_verdict,
    parse_date,
    parse_quantity,
)
from app.store import store

MIGRATION_MARK = "_rule_v2_backfilled"
# 存量装备按进场时间回填的基准：骨架日期从 2026-09-01 起按 id 顺延一天
LEGACY_ENTER_BASE = date(2026, 9, 1)

# 旧口径（v1）状态名：当时装备报废只减保有数量、不联动检查清单，
# 历史快照原样保留，不拿新口径改写。
LEGACY_STATUS_LABELS = {
    "合格可用": "合格可用",
    "需补充": "需补充",
    "已过期": "已过期",
    "已报废": "已报废",
}


def _backfill_rescue_row(row: dict[str, Any], index: int) -> bool:
    """回填一台存量装备；返回本次是否真的执行了迁移。"""
    if row.get(MIGRATION_MARK):
        return False

    # 进场时间：有合法值就尊重存量，否则按进场顺序回填
    if parse_date(row.get(ENTER_DATE_FIELD)) is None:
        row[ENTER_DATE_FIELD] = date.fromordinal(
            LEGACY_ENTER_BASE.toordinal() + index
        ).isoformat()

    # 骨架示例里的「应急救援样例N」不是日期，解析失败按进场时间补
    enter_date = parse_date(row[ENTER_DATE_FIELD]) or LEGACY_ENTER_BASE
    if parse_date(row.get(LAST_CHECK_FIELD)) is None:
        row[LAST_CHECK_FIELD] = enter_date.isoformat()
    if parse_date(row.get(NEXT_CHECK_FIELD)) is None:
        # 旧数据没有检查周期概念，回填时给一年周期；是否过期交给唯一口径判定
        next_date = date.fromordinal(enter_date.toordinal() + 365)
        row[NEXT_CHECK_FIELD] = next_date.isoformat()

    # 保有数量：非数字的样例值按 0 处理，确保旧脏数据也能进判定
    row[QUANTITY_FIELD] = parse_quantity(row.get(QUANTITY_FIELD))
    # 旧口径里已报废的行，报废事实迁移为显式标记
    row[SCRAPPED_FIELD] = bool(row.get(SCRAPPED_FIELD)) or row.get("status") == "已报废"

    legacy_status = LEGACY_STATUS_LABELS.get(str(row.get("status") or ""), "合格可用")
    # 旧结论按当时口径存档（只此一次），与 v2 结论并存
    row.setdefault(HISTORY_FIELD, []).insert(0, {
        "时间": row[ENTER_DATE_FIELD],
        "场景": "存量回填（按进场时间）",
        "口径版本": LEGACY_RULE_VERSION,
        "判定": "合格" if legacy_status == "合格可用" else "不合格",
        "判定状态": legacy_status,
        "命中规则": [],
        "生效规则": "",
    })

    # 当前结论统一由唯一口径重算，覆盖旧 status/装备状态
    apply_verdict(row)
    row[MIGRATION_MARK] = True
    return True


def run_backfill() -> dict[str, int]:
    """启动时执行：回填存量救援装备，返回迁移条数（已迁移过返回 0）。"""
    migrated = 0
    for index, row in enumerate(store.rows("rescue")):
        if _backfill_rescue_row(row, index):
            migrated += 1
    return {"rescue_backfilled": migrated}
