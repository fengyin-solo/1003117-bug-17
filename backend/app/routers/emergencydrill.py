"""应急演练接口：维护演练记录，装备清单的判定同步自应急救援统一口径。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.emergencydrill import EmergencydrillService

router = APIRouter(prefix="/api/emergencydrill", tags=["应急演练"])

service = EmergencydrillService()

LIST_FIELDS = ["演练编号", "演练主题", "演练区域", "参演人数", "演练日期", "装备清单摘要", "装备不合格数", "演练状态"]
STATUSES = ["待组织", "已组织", "已完成", "已复盘"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按演练编号检索"),
    status: str | None = Query(default=None, description="待组织、已组织、已完成、已复盘"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按演练编号与状态过滤应急演练列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出应急演练清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "emergencydrill", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条演练记录明细（含同步后的装备清单判定）。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"演练记录 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条演练记录，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="演练记录已登记", entry=entry)


@router.post("/{entry_id}/equipment", response_model=ActionResult)
def assign_equipment(entry_id: int, payload: EntryPayload) -> ActionResult:
    """把救援装备配到演练装备清单上；清单判定实时同步应急救援口径。"""
    ids = payload.values.get("装备id列表") or []
    if isinstance(ids, (str, int)):
        ids = [part.strip() for part in str(ids).split(",") if part.strip()]
    if not isinstance(ids, list):
        return ActionResult(ok=False, message="装备id列表需为数组或逗号分隔的 id")
    entry, message = service.assign_equipment(entry_id, ids)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条演练记录执行组织演练、完成演练、复盘总结；不允许的动作会被拦下。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
