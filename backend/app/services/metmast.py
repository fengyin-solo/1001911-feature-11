"""测风塔业务规则：停用/恢复状态机、操作记录与分时段数据完整率都收在这里。

状态只允许沿「数据缺失待复核 → 复核确认停用 → 复测恢复」依次流转，不允许跳级；
停用期间不允许提交校验。数据完整率按停用前后的采集时段分段封账，历史段保留当时
的采集口径，恢复后另起新段。
"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.store import store

MODULE = "metmast"
REQUIRED_FIELDS = ["塔架编号", "所在场站", "塔架高度"]
OPTIONAL_FIELDS = ["测风层数", "风速仪型号", "上次校验日"]

# 新塔先「待校验」；进入在运后，停用恢复只能沿后三个状态依次走，不允许跳级
STATUS_PENDING_CHECK = "待校验"
STATUS_NORMAL = "数据正常"
STATUS_MISSING = "数据缺失待复核"
STATUS_STOPPED = "复核确认停用"
STATUS_RECOVERED = "复测恢复"
STATUS_ORDER = [
    STATUS_PENDING_CHECK,
    STATUS_NORMAL,
    STATUS_MISSING,
    STATUS_STOPPED,
    STATUS_RECOVERED,
]

# 在运 = 已投运且当前不在停用态：缺数待复核期间塔架仍在运，待校验尚未投运
IN_SERVICE_STATUSES = {STATUS_NORMAL, STATUS_MISSING, STATUS_RECOVERED}
# 停用链上的动作：每执行一次都覆盖该塔「最近操作」，同塔连续操作只留最近一次
CHAIN_ACTIONS = ["登记数据缺失", "复核确认停用", "复测恢复"]

# 各状态下允许执行的动作；状态机只认当前状态的唯一后继，不允许跳级
ALLOWED_ACTIONS: dict[str, list[str]] = {
    STATUS_PENDING_CHECK: ["提交校验"],
    STATUS_NORMAL: ["登记数据缺失"],
    STATUS_MISSING: ["复核确认停用"],
    STATUS_STOPPED: ["复测恢复"],
    STATUS_RECOVERED: ["登记数据缺失"],
}

DEFAULT_CALIBER = "10分钟平均风速，按测风层数逐层统计，全年连续采集"


class MetmastService:
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
        page_rows = [self._decorate(dict(row)) for row in rows[start:start + size]]
        return page_rows, total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        return self._decorate(entry) if entry is not None else None

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry["status"] = STATUS_PENDING_CHECK
        entry["pending"] = True
        entry["abnormal"] = False
        for field in REQUIRED_FIELDS + OPTIONAL_FIELDS:
            if values.get(field) is not None:
                entry[field] = values.get(field)
        # 新塔还没有采集时段，完整率台账留空，校验通过投运后再开第一段
        entry["完整率台账"] = []
        entry["最近操作"] = None
        rows.append(entry)
        return self._decorate(entry), []

    def summary(self) -> dict[str, int]:
        """台账页顶部统计；在运口径与运营概览共用 in_service_count，两处必须一致。"""
        rows = store.rows(MODULE)
        return {
            "在运测风塔": self.in_service_count(),
            "数据缺失待复核": sum(1 for row in rows if row.get("status") == STATUS_MISSING),
            "复核确认停用": sum(1 for row in rows if row.get("status") == STATUS_STOPPED),
            "待校验": sum(1 for row in rows if row.get("status") == STATUS_PENDING_CHECK),
        }

    def in_service_count(self) -> int:
        """在运台数的唯一口径：未投运（待校验）与停用态都不计，缺数待复核仍计在运。"""
        return sum(1 for row in store.rows(MODULE) if row.get("status") in IN_SERVICE_STATUSES)

    def run_action(
        self,
        entry_id: int,
        action: str,
        values: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        values = values or {}
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"测风塔 {entry_id} 不存在或已归档"
        current = str(entry.get("status") or "")

        if action == "提交校验" and current == STATUS_STOPPED:
            return None, "测风塔处于停用期间，不允许提交校验；请先完成「复测恢复」"

        allowed = ALLOWED_ACTIONS.get(current, [])
        if action not in allowed:
            tail = f"，仅可执行：{'、'.join(allowed)}" if allowed else "，当前没有可执行动作"
            return None, f"当前状态「{current}」不允许执行「{action}」{tail}；状态只能按顺序流转，不允许跳级"

        today = date.today().isoformat()

        if action == "提交校验":
            entry["status"] = STATUS_NORMAL
            entry["pending"] = False
            entry["abnormal"] = False
            ledger = entry.setdefault("完整率台账", [])
            if not ledger:
                ledger.append({
                    "label": "当前采集时段",
                    "采集开始": today,
                    "采集结束": None,
                    "完整率": self._parse_rate(values.get("当前完整率")),
                    "采集口径": str(values.get("采集口径") or DEFAULT_CALIBER),
                })
            message = "测风塔校验通过，进入在运"

        elif action == "登记数据缺失":
            entry["status"] = STATUS_MISSING
            entry["pending"] = True
            entry["abnormal"] = True
            rate = self._parse_rate(values.get("当前完整率"))
            if rate is not None:
                segment = self._open_segment(entry)
                if segment is not None:
                    segment["完整率"] = rate
            self._record_op(entry, action, today, str(values.get("情况说明") or "").strip())
            message = "已登记数据缺失，等待复核确认是否停用"

        elif action == "复核确认停用":
            stop_time = str(values.get("停用时间") or today).strip()
            date_error = self._validate_date(stop_time, "停用时间")
            if date_error:
                return None, date_error
            segment = self._open_segment(entry)
            if segment is None:
                return None, "该塔没有进行中的采集时段，无法封账停用"
            if segment.get("采集开始") and stop_time < str(segment["采集开始"]):
                return None, f"停用时间不能早于本段采集开始时间（{segment['采集开始']}）"
            stop_no = sum(1 for seg in entry["完整率台账"] if str(seg.get("label", "")).startswith("停用前")) + 1
            segment["label"] = "停用前" if stop_no == 1 else f"停用前（第{stop_no}次）"
            segment["采集结束"] = stop_time
            rate = self._parse_rate(values.get("停用前完整率"))
            if rate is not None:
                segment["完整率"] = rate
            # 历史段完整率与采集口径到此封账，之后不再重算
            entry["status"] = STATUS_STOPPED
            entry["pending"] = True
            entry["abnormal"] = True
            entry["停用时间"] = stop_time
            entry["复核说明"] = str(values.get("复核说明") or "").strip()
            self._record_op(entry, action, stop_time, entry["复核说明"])
            message = "复核确认停用，停用前采集时段已按当时采集口径封账"

        else:  # 复测恢复：必须登记复测结论与恢复时间
            conclusion = str(values.get("复测结论") or "").strip()
            recover_time = str(values.get("恢复时间") or "").strip()
            if not conclusion:
                return None, "恢复使用必须登记复测结论"
            if not recover_time:
                return None, "恢复使用必须登记恢复时间"
            date_error = self._validate_date(recover_time, "恢复时间")
            if date_error:
                return None, date_error
            stop_time = entry.get("停用时间")
            if stop_time and recover_time < str(stop_time):
                return None, f"恢复时间不能早于停用时间（{stop_time}）"

            ledger = entry.setdefault("完整率台账", [])
            recover_no = sum(1 for seg in ledger if str(seg.get("label", "")).startswith("停用前"))
            label = "恢复后" if recover_no == 1 else f"恢复后（第{recover_no}次）"
            previous = self._last_segment(entry)
            ledger.append({
                "label": label,
                "采集开始": recover_time,
                "采集结束": None,
                "完整率": self._parse_rate(values.get("恢复后完整率")),
                # 新采集时段可以换口径；不填则沿用上一段口径，历史段口径原样保留
                "采集口径": str(values.get("采集口径") or (previous or {}).get("采集口径") or DEFAULT_CALIBER),
            })
            entry["status"] = STATUS_RECOVERED
            entry["pending"] = False
            entry["abnormal"] = False
            entry["恢复时间"] = recover_time
            entry["复测结论"] = conclusion
            self._record_op(entry, action, recover_time, conclusion)
            message = "复测结论已登记，测风塔恢复使用"

        return self._decorate(entry), message

    # ---- 内部辅助 ----------------------------------------------------------

    def _decorate(self, entry: dict[str, Any]) -> dict[str, Any]:
        """读出时同步出列表用的展示字段：分段完整率与测风状态。"""
        entry.setdefault("完整率台账", [])
        entry["数据完整率"] = self._format_rate(entry["完整率台账"])
        entry["测风状态"] = entry.get("status")
        return entry

    def _record_op(self, entry: dict[str, Any], action: str, op_time: str, note: str) -> None:
        """停用/恢复操作只留最近一次：后一次动作直接覆盖前一次记录。"""
        entry["最近操作"] = {"动作": action, "时间": op_time, "说明": note}

    def _open_segment(self, entry: dict[str, Any]) -> dict[str, Any] | None:
        for segment in reversed(entry.get("完整率台账", [])):
            if not segment.get("采集结束"):
                return segment
        return None

    def _last_segment(self, entry: dict[str, Any]) -> dict[str, Any] | None:
        ledger = entry.get("完整率台账") or []
        return ledger[-1] if ledger else None

    def _format_rate(self, ledger: list[dict[str, Any]]) -> str:
        """完整率按采集时段分开呈现：停用前/恢复后各算各的，互不混算。"""
        if not ledger:
            return "待采集"
        parts: list[str] = []
        for segment in ledger:
            rate = segment.get("完整率")
            tail = f"{rate}%" if rate is not None else "采集中"
            parts.append(f"{segment.get('label')} {tail}")
        return "；".join(parts)

    def _parse_rate(self, value: Any) -> float | None:
        if value is None or str(value).strip() == "":
            return None
        try:
            return round(float(str(value).strip().rstrip("%")), 1)
        except (TypeError, ValueError):
            return None

    def _validate_date(self, value: str, field_name: str) -> str:
        try:
            date.fromisoformat(value)
        except ValueError:
            return f"{field_name}格式应为 YYYY-MM-DD"
        return ""
