"""测风塔接口：维护测风塔，覆盖提交校验、登记数据缺失、复核确认停用、复测恢复等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.metmast import MetmastService

router = APIRouter(prefix="/api/metmast", tags=["测风塔"])

service = MetmastService()

LIST_FIELDS = ["塔架编号", "所在场站", "塔架高度", "测风层数", "风速仪型号", "上次校验日", "停用前数据完整率", "恢复后数据完整率", "测风状态"]


@router.get("/stats")
def get_stats() -> dict[str, Any]:
    """台账页统计卡片；在运台数口径与运营概览共用同一实现。"""
    return service.stats()


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按塔架编号检索"),
    status: str | None = Query(default=None, description="在运、数据缺失待复核、复核确认停用、复测恢复"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按塔架编号与状态过滤测风塔列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出测风塔清单：返回当前过滤条件下的全量数据。须排在 /{entry_id} 之前，避免被当作编号。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "metmast", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条测风塔明细；不存在时给出可读的错误说明。停用后塔架高度、测风层数仍可查看。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"测风塔 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条测风塔，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="测风塔已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条测风塔执行动作；状态只能按流水线依次推进，停用期间不允许提交校验。

    复测恢复必须随 payload.values 提交「复测结论」与「恢复时间」。
    """
    action = str(payload.values.pop("action", "") or "").strip()
    entry, message = service.run_action(entry_id, action, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
