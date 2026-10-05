"""救援装备合格判定的唯一口径。

所有入口（救援装备列表、装备详情、应急演练装备清单、入井名单）需要判定一台
救援装备是否合格时，都只能走这里的 evaluate，不允许各自下结论。

两条判定合成一份，且不能各自生效：
  1. 保有数量降到零          → 已报废（不合格）
  2. 下次检查日早于判定基准日 → 已过期（不合格）
  3. 其余                    → 合格可用（合格）

同一台装备同时命中两条时结论会冲突（按数量是已报废、按检查日是已过期），
以过期的那条为准。旧口径下的「需补充」仅作为历史结论保留，当前规则不再
单独产生它（数量大于零且未过期时仍按合格可用计）。

旧结论按当时的口径保留在装备的判定历史里（judgement_history，只追加不改写），
列表和详情读出的永远是同一份 evaluate 结果。
"""
from __future__ import annotations

from datetime import date
from typing import Any, Callable

# 判定口径版本：规则改动只在这里发生，改一份两个入口（列表/详情）一起变。
RULE_VERSION = "2026-10 统一口径"
LEGACY_RULE_VERSION = "旧口径（保有数量与检查日分别判定）"

# 结论取值（顺序即冲突时的优先级，越靠前优先级越高）。
JUDGEMENT_EXPIRED = "已过期"
JUDGEMENT_SCRAPPED = "已报废"
JUDGEMENT_QUALIFIED = "合格可用"
# 旧口径遗留结论：新规则不再产生，但旧记录里可能带着。
JUDGEMENT_NEED_SUPPLY = "需补充"

UNQUALIFIED_JUDGEMENTS = (JUDGEMENT_EXPIRED, JUDGEMENT_SCRAPPED, JUDGEMENT_NEED_SUPPLY)

REASON_EXPIRED = "下次检查日已过期"
REASON_ZERO_STOCK = "保有数量为零（已报废）"
REASON_QUALIFIED = "保有数量大于零且检查日未过期"

DEFAULT_EVAL_DATE = date(2026, 10, 5)


def parse_date(value: Any) -> date | None:
    """尽量把 2026-10-05 这类值解析成日期；解析不了（含占位样例文本）返回 None。"""
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def parse_quantity(value: Any) -> int | None:
    """把保有数量解析成非负整数；无法解析（含样例文本）返回 None。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return max(value, 0)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return max(int(float(text)), 0)
    except ValueError:
        return None


def evaluate(
    entry: dict[str, Any],
    *,
    as_of: date | None = None,
    clock: Callable[[], date] = date.today,
) -> dict[str, Any]:
    """对一台装备做一次完整判定，列表和详情共用这一份结论。

    返回 qualified / judgement / reasons / matched / as_of。
    matched 列出命中的原始判定（可能同时有两条），judgement 是冲突裁决后的
    唯一结论——两条同时命中时以「已过期」为准。
    """
    as_of = as_of or clock()
    quantity = parse_quantity(entry.get("保有数量"))
    next_check = parse_date(entry.get("下次检查日"))

    zero_stock = quantity is not None and quantity <= 0
    expired = next_check is not None and next_check < as_of

    matched: list[str] = []
    reasons: list[str] = []
    if zero_stock:
        matched.append(JUDGEMENT_SCRAPPED)
        reasons.append(REASON_ZERO_STOCK)
    if expired:
        matched.append(JUDGEMENT_EXPIRED)
        reasons.append(REASON_EXPIRED)

    # 两条合一份：同时命中时以过期的那条为准。
    if expired:
        judgement = JUDGEMENT_EXPIRED
    elif zero_stock:
        judgement = JUDGEMENT_SCRAPPED
    else:
        judgement = JUDGEMENT_QUALIFIED
        reasons.append(REASON_QUALIFIED)

    return {
        "qualified": judgement == JUDGEMENT_QUALIFIED,
        "judgement": judgement,
        "matched": matched,
        "reasons": reasons,
        "as_of": as_of.isoformat(),
        "rule_version": RULE_VERSION,
    }


def inspection_dates_valid(last_check: Any, next_check: Any) -> bool:
    """保存检查记录的硬约束：下次检查日不得早于上次检查。

    缺任一端日期时不在这里拦截（由必填校验负责）；只要两端都能解析，
    就必须满足 下次检查日 >= 上次检查。
    """
    last_date = parse_date(last_check)
    next_date = parse_date(next_check)
    if last_date is None or next_date is None:
        return True
    return next_date >= last_date
