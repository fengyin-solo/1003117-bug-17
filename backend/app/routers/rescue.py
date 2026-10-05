# -*- coding: utf-8 -*-
"""应急救援接口：维护救援装备，覆盖登记检查、补充装备、申请报废等动作。

判定结果不在接口层计算，全部来自 ``app.services.rescue`` → ``app.rules``
这同一条链路，列表、详情、演练清单、入井名单读到的口径一致。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.rescue import RescueService

router = APIRouter(prefix="/api/rescue", tags=["应急救援"])

service = RescueService()

LIST_FIELDS = ["装备编号", "装备名称", "装备类别", "存放地点", "保有数量", "上次检查", "下次检查日", "装备状态"]
# 判定状态由 app.rules 唯一口径产出
STATUSES = ["合格可用", "已过期", "无保有量", "已报废"]


@router.get("/stats")
def stats() -> dict[str, int]:
    """按统一口径汇总合格/归零/过期/报废与待检数量。"""
    return service.stats()


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按装备编号检索"),
    status: str | None = Query(default=None, description="合格可用、已过期、无保有量、已报废"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按装备编号与判定状态过滤应急救援列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    if status and status not in STATUSES:
        raise HTTPException(status_code=400, detail=f"判定状态仅支持：{'、'.join(STATUSES)}")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出应急救援清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "rescue", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条救援装备明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"救援装备 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条救援装备，缺字段时说明原因而不是静默丢弃。"""
    entry, errors = service.create_entry(payload.values)
    if errors:
        message = errors[0] if "已存在" in errors[0] else f"缺少必填字段：{'、'.join(errors)}"
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message="救援装备已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条救援装备执行登记检查、补充装备、申请报废。

    - 登记检查：下次检查日不得早于上次检查，倒挂直接拒绝；
    - 申请报废：重复提交幂等，只生效一次；
    - 动作完成后按统一口径重算判定，同步影响演练清单与入井名单。
    """
    values = dict(payload.values)
    action = str(values.pop("action", "") or "").strip()
    entry, message = service.run_action(entry_id, action, values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
