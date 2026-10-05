"""应急救援接口：维护救援装备，覆盖登记检查、补充装备、申请报废等动作。

列表与详情返回的判定都来自 service.serialize（唯一口径），路由层不做业务判断。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.rescue import get_rescue_service

router = APIRouter(prefix="/api/rescue", tags=["应急救援"])

service = get_rescue_service()

LIST_FIELDS = ["装备编号", "装备名称", "装备类别", "存放地点", "保有数量", "上次检查", "下次检查日", "判定"]
STATUSES = ["合格可用", "需补充", "已过期", "已报废"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按装备编号检索"),
    status: str | None = Query(default=None, description="合格可用、已过期、已报废"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按装备编号与判定过滤应急救援列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/stats")
def judgement_stats() -> dict[str, Any]:
    """按统一口径汇总合格、过期、报废、待检数量。"""
    return {"module": "rescue", **service.stats()}


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
    """登记一条救援装备，缺字段或检查日期倒挂时说明原因而不是静默丢弃。"""
    entry, message = service.create_entry(payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message="救援装备已登记", entry=entry)


@router.post("/{entry_id}/inspections", response_model=ActionResult)
def record_inspection(entry_id: int, payload: EntryPayload) -> ActionResult:
    """保存检查记录；下次检查日早于上次检查时拒绝保存。"""
    entry, message = service.record_inspection(
        entry_id,
        str(payload.values.get("上次检查") or ""),
        str(payload.values.get("下次检查日") or ""),
    )
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条救援装备执行登记不足、补充装备、申请报废；重复报废只生效一次。"""
    action = str(payload.values.pop("action", "") or "").strip()
    entry, message = service.run_action(entry_id, action, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
