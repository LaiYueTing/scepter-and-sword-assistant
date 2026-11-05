"""把背景執行緒的紀錄、狀態、任務卡推到前端：Python → `window.__recv([{event, data}, ...])`。

⚠ 紀錄要批次推送：evaluate_js 單次約 1～2 毫秒，逐行送會拖慢規則引擎。
  紀錄進佇列，由 `_pump` 每 `FLUSH` 秒送一批；狀態與任務卡立刻送。
"""

from __future__ import annotations

import json
import logging
import queue
import threading
from typing import Any

from core import logger

FLUSH = 0.2          # 紀錄批次推送的間隔（秒）
MAX_BATCH = 400      # 單批上限


def to_js(payload: Any) -> str:
    """把資料轉成能安全嵌進 JS 的字面量。

    ⚠ 保留 `ensure_ascii=True`：U+2028 / U+2029 在 JS 原始碼裡是換行字元。
    """
    return json.dumps(payload, ensure_ascii=True)


class Channel:
    """通往前端的單向通道，視窗就緒前先把訊息存著。"""

    def __init__(self) -> None:
        self._window = None
        self._logs: queue.Queue[dict] = queue.Queue()
        self._alive = threading.Event()
        self._pending: list[dict] = []      # 視窗就緒前的訊息
        self._lock = threading.Lock()
        self._closed = False        # 視窗已關閉，見 _emit

    def attach(self, window) -> None:
        """視窗就緒後接上，並補送等待中的訊息。"""
        self._window = window
        self._alive.set()
        threading.Thread(target=self._pump, daemon=True).start()

    def close(self) -> None:
        self._alive.clear()
        self._closed = True

    # ---------- 對外：推事件 ----------

    def log(self, level: str, module: str, msg: str, ts: float) -> None:
        """紀錄走佇列，由 `_pump` 批次送出。"""
        self._logs.put({"level": level, "module": module, "msg": msg, "ts": ts})

    def send(self, event: str, data: Any = None) -> None:
        """狀態、任務卡這類低頻事件，立刻送。"""
        self._emit([{"event": event, "data": data}])

    # ---------- 內部 ----------

    def _emit(self, events: list[dict]) -> None:
        if not events:
            return
        with self._lock:
            if self._window is None:
                self._pending.extend(events)
                return
            if self._closed:
                return
            try:
                self._window.evaluate_js(f"window.__recv({to_js(events)})")
            except Exception:
                # 視窗關閉的瞬間仍可能有事件在路上，例外不影響結束程序。
                # ⚠ 失敗一次就不再試：ObjectDisposedException 會由 pywebview 寫進紀錄。
                self._closed = True

    def _pump(self) -> None:
        """把佇列裡的紀錄整批送出。"""
        # 先補送視窗接上前累積的訊息
        with self._lock:
            pending, self._pending = self._pending, []
        self._emit(pending)

        while self._alive.is_set():
            batch: list[dict] = []
            try:
                batch.append(self._logs.get(timeout=FLUSH))
            except queue.Empty:
                continue
            while len(batch) < MAX_BATCH:
                try:
                    batch.append(self._logs.get_nowait())
                except queue.Empty:
                    break
            self._emit([{"event": "log", "data": batch}])


class WebLogHandler(logging.Handler):
    """把 logging 的每一筆轉成通道事件。不套 formatter，介面用原始欄位排版。"""

    def __init__(self, channel: Channel):
        super().__init__()
        self.channel = channel

    def emit(self, record: logging.LogRecord) -> None:
        # ⚠ 只放行專案自己的模組（`logger.is_known_module`）：root logger 收得到第三方紀錄。
        if not logger.is_known_module(record.name):
            return
        try:
            self.channel.log(
                logger.level_label(record.levelname),
                logger.module_label(record.name),
                record.getMessage(),
                record.created,
            )
        except Exception:
            pass      # 紀錄的例外不影響腳本
