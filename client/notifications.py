"""报告通知的 SSE 订阅线程。

主账号在后台保持一条长连接:收到新报告事件后立即触发本地同步,
断线按 1s → 2s → 5s → 10s → 30s 退避重连。进程退出时通过 stop() 停止。
"""

from __future__ import annotations

import json
import logging
import threading

logger = logging.getLogger(__name__)

BACKOFF_SECONDS = (1, 2, 5, 10, 30)
REPORT_EVENTS = ("report.created", "report.updated", "report.deleted")
CONTENT_EVENTS = ("content.updated",)
STREAM_EVENTS = REPORT_EVENTS + CONTENT_EVENTS


class ReportStream:
    """后台订阅后端报告事件并回调。"""

    def __init__(
        self,
        gateway,
        on_event,
        *,
        backoff=BACKOFF_SECONDS,
        stop_event=None,
        thread_factory=None,
    ):
        self.gateway = gateway
        self.on_event = on_event
        self.backoff = tuple(backoff) or (30,)
        self._stop = stop_event or threading.Event()
        self._thread_factory = thread_factory
        self._thread = None

    # ---- 生命周期 ----
    def start(self) -> None:
        if self._thread is not None:
            return
        if self._thread_factory is None:
            thread = threading.Thread(target=self._run, name="report-stream", daemon=True)
            thread.start()
        else:
            thread = self._thread_factory(self._run)
            if thread is not None and hasattr(thread, "start"):
                thread.start()
        self._thread = thread or True

    def stop(self, timeout: float | None = 1.0) -> None:
        self._stop.set()
        thread = self._thread
        if isinstance(thread, threading.Thread) and thread.is_alive():
            thread.join(timeout=timeout)
        self._thread = None

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    # ---- 主循环 ----
    def _run(self) -> None:
        attempt = 0
        while not self._stop.is_set():
            try:
                for event in self.gateway.stream_report_events():
                    if self._stop.is_set():
                        return
                    attempt = 0
                    self._dispatch(event)
            except Exception:
                if self._stop.is_set():
                    return
                logger.debug("报告通知长连接中断,准备重连", exc_info=True)
            delay = self.backoff[min(attempt, len(self.backoff) - 1)]
            attempt += 1
            if self._stop.wait(delay):
                return

    def _dispatch(self, event) -> None:
        if not isinstance(event, dict):
            return
        name = str(event.get("event") or "")
        if name not in STREAM_EVENTS:
            return
        payload = event.get("data")
        if isinstance(payload, str):
            try:
                payload = json.loads(payload) if payload else {}
            except ValueError:
                payload = {}
        data = {"event": name, "data": payload or {}}
        try:
            self.on_event(data)
        except Exception:
            logger.debug("处理报告事件失败 event=%s", name, exc_info=True)
