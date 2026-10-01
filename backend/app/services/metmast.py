"""测风塔业务规则：停用/恢复状态机、字段校验、完整率分段统计与在运口径都收在这里。

状态只能沿固定流水线推进，不允许跳级：

    在运 ──登记数据缺失──▶ 数据缺失待复核 ──复核确认停用──▶ 复核确认停用
      ▲                                                      │
      └──────────────────复测恢复（登记复测结论+恢复时间）──────┘

停用期间（复核确认停用）不允许提交校验；恢复后进入「复测恢复」在运状态，
可继续提交校验，也可再次登记数据缺失，流程可以循环。
"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.store import store

MODULE = "metmast"
REQUIRED_FIELDS = ["塔架编号", "所在场站", "塔架高度"]

# 停用/恢复流水线状态
STATUS_ACTIVE = "在运"
STATUS_MISSING = "数据缺失待复核"
STATUS_STOPPED = "复核确认停用"
STATUS_RESUMED = "复测恢复"
# 状态推进顺序，跳级一律拒绝
STATUS_FLOW = [STATUS_MISSING, STATUS_STOPPED, STATUS_RESUMED]
# 可筛选的全部测风状态（在运与复测恢复都属于在运，区分口径但都计入在运台数）
STATUSES = [STATUS_ACTIVE, STATUS_MISSING, STATUS_STOPPED, STATUS_RESUMED]

ACTION_REGISTER_MISSING = "登记数据缺失"
ACTION_CONFIRM_STOP = "复核确认停用"
ACTION_RESUME = "复测恢复"
ACTION_VERIFY = "提交校验"


def _today() -> str:
    return date.today().isoformat()


class MetmastService:
    # ---- 查询 ----------------------------------------------------------
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
            rows = [row for row in rows if keyword in str(row.get("塔架编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return [self._present(row) for row in rows[start:start + size]], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        return self._present(entry, include_history=True) if entry else None

    # ---- 登记 ----------------------------------------------------------
    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        # 选填的台账字段一并保存，停用后仍可查看
        for field in ["测风层数", "风速仪型号"]:
            if values.get(field):
                entry[field] = values.get(field)
        entry["status"] = STATUS_ACTIVE
        entry["pending"] = False
        entry["abnormal"] = False
        # 采集时段分段：每段记起止时间与当时口径下的完整率，历史段冻结不改
        entry["segments"] = [{"start": _today(), "end": None, "数据完整率": values.get("数据完整率") or "—"}]
        entry["last_action"] = None
        rows.append(entry)
        return self._present(entry), []

    # ---- 动作 ----------------------------------------------------------
    def run_action(self, entry_id: int, action: str, values: dict[str, Any] | None = None) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"测风塔 {entry_id} 不存在或已归档"
        values = values or {}
        status = str(entry.get("status") or "")

        if action == ACTION_VERIFY:
            return self._verify(entry, values)
        if action == ACTION_REGISTER_MISSING:
            return self._advance(entry, STATUS_MISSING, action, values)
        if action == ACTION_CONFIRM_STOP:
            return self._advance(entry, STATUS_STOPPED, action, values)
        if action == ACTION_RESUME:
            return self._resume(entry, values)
        return None, f"动作「{action}」不属于测风塔可执行范围"

    def _verify(self, entry: dict[str, Any], values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        """提交校验：停用期间一律不受理；只登记校验日，不改变停用/恢复流水线状态。"""
        if entry.get("status") == STATUS_STOPPED:
            return None, "测风塔处于复核确认停用期间，不允许提交校验；请先完成复测恢复"
        verify_date = str(values.get("校验日期") or _today()).strip()
        entry["上次校验日"] = verify_date
        # 校验不覆盖停用/恢复操作记录，列表页操作记录列只随流水线动作更新
        return self._present(entry), "校验已提交"

    def _advance(
        self,
        entry: dict[str, Any],
        target: str,
        action: str,
        values: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, str]:
        """沿流水线向前推进一步；不在相邻前序状态上的请求视为跳级，直接拒绝。"""
        status = str(entry.get("status") or "")
        if target == STATUS_FLOW[0]:
            # 数据缺失待复核是流水线入口，在运（含复测恢复）塔都可登记
            allowed = status in (STATUS_ACTIVE, STATUS_RESUMED)
        else:
            # 其余步骤只能由流水线中的相邻前序状态推进
            allowed = status == STATUS_FLOW[STATUS_FLOW.index(target) - 1]
        if not allowed:
            return None, f"当前状态为「{status}」，不能直接{action}；状态须依次经{'、'.join(STATUS_FLOW)}，不允许跳级"

        occurred = str(values.get("操作时间") or _today()).strip()
        if target == STATUS_MISSING:
            rate = str(values.get("数据完整率") or "").strip()
            if rate:
                self._current_segment(entry)["数据完整率"] = rate
            entry["pending"] = True
            entry["abnormal"] = True
            note = f"数据完整率 {rate}" if rate else "采集数据缺失"
        else:
            # 复核确认停用：冻结当前采集时段
            self._close_current_segment(entry, occurred)
            entry["pending"] = True
            entry["abnormal"] = True
            note = str(values.get("停用原因") or "复核确认停用").strip()
        entry["status"] = target
        self._set_action(entry, action, occurred, note=note)
        return self._present(entry), f"测风塔已{action}"

    def _resume(self, entry: dict[str, Any], values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        """复测恢复：必须登记复测结论与恢复时间，并开启恢复后的新采集时段。"""
        if entry.get("status") != STATUS_STOPPED:
            return None, (
                f"当前状态为「{entry.get('status')}」，不能直接复测恢复；"
                f"只有复核确认停用的测风塔才能登记复测恢复"
            )
        conclusion = str(values.get("复测结论") or "").strip()
        recover_time = str(values.get("恢复时间") or "").strip()
        missing = [name for name, val in (("复测结论", conclusion), ("恢复时间", recover_time)) if not val]
        if missing:
            return None, f"恢复使用必须登记{'、'.join(missing)}，请补充后再提交"
        rate = str(values.get("数据完整率") or "").strip()

        entry["status"] = STATUS_RESUMED
        entry["pending"] = False
        entry["abnormal"] = False
        entry["复测结论"] = conclusion
        entry["恢复时间"] = recover_time
        # 恢复后另开采集时段，停用前后的完整率分开统计
        entry.setdefault("segments", []).append(
            {"start": recover_time, "end": None, "数据完整率": rate or "—"}
        )
        self._set_action(entry, ACTION_RESUME, recover_time, note=f"复测结论：{conclusion}")
        return self._present(entry), "复测恢复已登记，测风塔重新投入使用"

    # ---- 统计 ----------------------------------------------------------
    def stats(self) -> dict[str, int]:
        """在运台数的唯一口径：除「复核确认停用」外全部在运。

        概览看板与测风塔台账（列表页）共用本方法，两处数字始终一致。
        """
        rows = store.rows(MODULE)
        active = sum(1 for row in rows if row.get("status") != STATUS_STOPPED)
        missing = sum(1 for row in rows if row.get("status") == STATUS_MISSING)
        stopped = sum(1 for row in rows if row.get("status") == STATUS_STOPPED)
        return {"total": len(rows), "active": active, "missing": missing, "stopped": stopped}

    # ---- 内部工具 ------------------------------------------------------
    def _current_segment(self, entry: dict[str, Any]) -> dict[str, Any]:
        segments = entry.setdefault("segments", [])
        if not segments:
            segments.append({"start": _today(), "end": None, "数据完整率": "—"})
        return segments[-1]

    def _close_current_segment(self, entry: dict[str, Any], end: str) -> None:
        seg = self._current_segment(entry)
        seg["end"] = end

    def _set_action(self, entry: dict[str, Any], action: str, when: str, *, note: str = "") -> None:
        """同一座测风塔连续的停用/恢复操作只记最近一次，直接覆盖 last_action。"""
        entry["last_action"] = {"action": action, "time": when, "note": note}

    def _present(self, entry: dict[str, Any], *, include_history: bool = False) -> dict[str, Any]:
        """出参：塔架高度、测风层数停用后照常返回；完整率按停用前/恢复后两段给出口径。

        include_history 时附带全部历史采集时段（每段完整率按当时口径冻结，不再改写）。
        """
        data = dict(entry)
        segments = list(entry.get("segments") or [])
        closed = [seg for seg in segments if seg.get("end")]
        open_seg = next((seg for seg in reversed(segments) if seg.get("end") is None), None)
        if entry.get("status") == STATUS_STOPPED:
            # 停用中：停用前时段已冻结，恢复后时段尚未开始
            data["停用前数据完整率"] = closed[-1]["数据完整率"] if closed else "—"
            data["恢复后数据完整率"] = "停用中，暂无采集"
        elif closed:
            # 已恢复：停用前按冻结口径展示，恢复后取当前采集时段
            data["停用前数据完整率"] = closed[-1]["数据完整率"]
            data["恢复后数据完整率"] = open_seg["数据完整率"] if open_seg else "—"
        else:
            # 从未停用：当前采集时段即停用前时段
            data["停用前数据完整率"] = open_seg["数据完整率"] if open_seg else "—"
            data["恢复后数据完整率"] = "—"
        data["测风状态"] = entry.get("status")
        if include_history:
            # 明细页保留历史完整率：各采集时段的完整率按当时口径冻结
            data["历史采集时段"] = [dict(seg) for seg in segments]
        data.pop("segments", None)
        return data
