"""把跑在背景執行緒的東西（紀錄、狀態、任務卡）推到前端。

通道只有一個方向：Python → `window.__recv([{event, data}, ...])`。前端要叫後端做事
走的是另一條路（pywebview 的 `js_api`，見 `gui/api.py`）。

⚠ **紀錄一定要批次推送。** 每來一行就 `evaluate_js` 一次的話，一次呼叫要跨
   Python → CLR → WebView2 三層，實測單次約 1～2 毫秒；副本開場那種一秒好幾行的
   時候會把工作執行緒拖住，而那條執行緒正在跑規則引擎。所以紀錄先進佇列，由
   `_pump` 每 `FLUSH` 秒送一批。狀態與任務卡不批次——它們本來就低頻，而且要即時。
"""

from __future__ import annotations

import json
import logging
import queue
import threading
from typing import Any

from core import logger

FLUSH = 0.2          # 紀錄批次推送的間隔（秒）
MAX_BATCH = 400      # 單批上限，避免一次塞爆 evaluate_js


def to_js(payload: Any) -> str:
    """把資料變成能安全嵌進 JS 的字面量。

    ⚠ U+2028 / U+2029 在 JSON 裡合法，在 JS 原始碼裡卻是換行字元，直接嵌進去會
      讓那一行語法錯誤。`ensure_ascii=True` 會把它們一起轉成 \\u 逸出，所以這裡
      刻意不關掉——中文變成 \\uXXXX 只是字面量變長，解出來仍是原字。
    """
    return json.dumps(payload, ensure_ascii=True)


class Channel:
    """通往網頁那一側的單向通道。視窗還沒建好之前先把訊息存著。"""

    def __init__(self) -> None:
        self._window = None
        self._logs: queue.Queue[dict] = queue.Queue()
        self._alive = threading.Event()
        self._pending: list[dict] = []      # 視窗就緒前的訊息
        self._lock = threading.Lock()
        self._closed = False        # 視窗沒了就不要再推事件，見 _emit

    def attach(self, window) -> None:
        """視窗建好之後接上，並把等待中的訊息補送出去。

        ⚠ **沒有這個佇列，介面會停在載入畫面。** 後端在視窗畫完之前就會寫東西
          （設定說明、「哪些規則因設定而不啟用」），丟掉的話使用者永遠看不到；
        """
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
                # 視窗關閉的瞬間仍可能有事件在路上。介面掛掉不該把腳本一起帶走
                # ——收尾動作還在跑，那才是不能中斷的部分。
                #
                # ⚠ **失敗一次就不要再試。** WebView2 被處置之後每一發
                #   `evaluate_js` 都會丟 .NET 的 `ObjectDisposedException`，而那是
                #   pywebview 自己用 logging 印的——會**一路寫進 assistant.log**，
                #   把使用者真正要查的東西擠掉。（我們的 handler 有過濾模組，
                #   但 root logger 的檔案 handler 收得到所有人的紀錄。）
                self._closed = True

    def _pump(self) -> None:
        """把佇列裡的紀錄整批送出。"""
        # 視窗剛接上，先補送等待期間累積的訊息
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
    """把 logging 的每一筆轉成通道事件。

    刻意不套 formatter：終端機那份格式是為等寬字型的欄位對齊設計的
    （`logger.pad()` 按顯示寬度補空白），網頁用比例字型，補空白只會歪。介面拿到
    原始欄位自己排版。
    """

    def __init__(self, channel: Channel):
        super().__init__()
        self.channel = channel

    def emit(self, record: logging.LogRecord) -> None:
        # ⚠ 只放行專案自己的模組。掛在 root logger 上收得到所有人的紀錄，而
        #   pywebview 自己就用 logging——`debug=True` 時它每個事件都寫一行
        #   （「loaded event fired」那種），實測 15 行的執行紀錄被灌成 22 行。
        #   判斷交給 `logger.is_known_module`，和「取 logger 一定要用對照表裡的
        #   鍵」是同一份來源，不另外維護第二份清單。
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
            pass      # 紀錄自己壞掉不該把腳本一起帶走
