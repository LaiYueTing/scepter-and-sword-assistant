"""單一實例：同一時間只允許一個助手操作模擬器。

鎖是具名 mutex，「把既有視窗叫回前景」走具名 event，兩者都是 kernel 物件，
不開連接埠、不靠視窗標題，介面與命令列共用同一把。

    lock = singleton.acquire(windowed=True)
    if lock is None:                      # 已經有一個在跑
        singleton.wake_existing()         # 把那個視窗叫回前景
        return 0
    lock.listen(叫回自己視窗的函式)        # 視窗建好之後接上

⚠ `windowed` 在取得鎖的當下就要指定：視窗還在建立時，第二個行程也要敲得到門。
⚠ 名稱不分開發版與打包版，兩者操作的是同一台模擬器。
⚠ 只掛在會操作裝置的執行上（介面與 run），doctor、explain、find、selftest 不上鎖。
"""

from __future__ import annotations

import ctypes
import sys
import threading
import time
from ctypes import wintypes
from typing import Callable

from . import logger

log = logger.get("main")

_NAME = "ScepterSwordAssistant"

# 先試 Global 再退 Local：工作排程器可能跑在 session 0，只有 Global 看得到彼此。
_SCOPES = ("Global\\", "Local\\")

_ERROR_ALREADY_EXISTS = 183
_EVENT_MODIFY_STATE = 0x0002
_WAIT_OBJECT_0 = 0
_INFINITE = 0xFFFFFFFF

_held: "Lock | None" = None


def _kernel32():
    """取得 kernel32，非 Windows 或載入失敗時回傳 None（此時不擋）。"""
    if not sys.platform.startswith("win"):
        return None
    try:
        k = ctypes.WinDLL("kernel32", use_last_error=True)
    except (AttributeError, OSError):
        return None

    # ⚠ 一定要宣告 restype：預設 int 會截掉 64 位 handle 的高位元。
    k.CreateMutexW.restype = wintypes.HANDLE
    k.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    k.CreateEventW.restype = wintypes.HANDLE
    k.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL,
                               wintypes.LPCWSTR]
    k.OpenEventW.restype = wintypes.HANDLE
    k.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    k.SetEvent.argtypes = [wintypes.HANDLE]
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    k.WaitForSingleObject.restype = wintypes.DWORD
    k.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    return k


class Lock:
    """握在手上的鎖。⚠ 呼叫端要保留參考，物件被回收等於解鎖（模組層級的 `_held` 也留一份）。"""

    def __init__(self, k, mutex, wake_name: str) -> None:
        self._k = k
        self._mutex = mutex
        self._wake_name = wake_name
        self._wake = None
        self._on_wake: Callable[[], None] | None = None
        self._knocked = False               # 回呼接上之前的敲門記錄
        self._guard = threading.Lock()

    def open_door(self) -> None:
        """開始接受「把視窗叫回來」的敲門，可重複呼叫。

        回呼接上之前的敲門記在 `_knocked`，由 `listen()` 補叫。
        ⚠ 命令列的 run 不開門：它沒有視窗可叫，第二個實例要敲不到才會自己說明。
        """
        if self._k is None or self._wake is not None or not self._wake_name:
            return
        # 自動重設（第二個參數 False）：敲一次醒一次
        self._wake = self._k.CreateEventW(None, False, False, self._wake_name)
        if not self._wake:
            return

        def loop() -> None:
            while True:
                if self._k.WaitForSingleObject(self._wake, _INFINITE) != _WAIT_OBJECT_0:
                    return
                with self._guard:
                    callback = self._on_wake
                    if callback is None:
                        self._knocked = True
                        continue
                try:
                    callback()
                except Exception as e:      # 介面的例外不影響腳本
                    log.warning("叫回視窗失敗：%s", e)

        threading.Thread(target=loop, daemon=True).start()

    def listen(self, on_wake: Callable[[], None]) -> None:
        """視窗建好之後接上回呼，每敲一次門就呼叫 on_wake 一次。

        ⚠ on_wake 跑在等門的背景執行緒上（接上之前的敲門則跑在呼叫 listen 的執行緒），
          要碰介面就得切回主執行緒（pywebview 的視窗方法會自己切換）。
        """
        with self._guard:
            self._on_wake = on_wake
            pending, self._knocked = self._knocked, False
        if pending:
            on_wake()

    def release(self) -> None:
        """釋放鎖。行程結束時系統也會收回，這是給測試與明確釋放用的。"""
        global _held
        for handle in (self._wake, self._mutex):
            if handle and self._k is not None:
                self._k.CloseHandle(handle)
        self._wake = self._mutex = None
        if _held is self:
            _held = None


def acquire(windowed: bool = False) -> Lock | None:
    """取得鎖；已經有別的行程握著就回傳 None。`windowed` 表示之後會有視窗可叫回前景。

    ⚠ 同一個行程重複呼叫會拿到同一把（`main.py` 與 `gui/app.py` 兩層都會呼叫）。
    """
    global _held
    if _held is not None:
        if windowed:
            _held.open_door()
        return _held

    k = _kernel32()
    if k is None:
        _held = Lock(None, None, "")        # 無法上鎖時不擋，不影響啟動
        return _held

    for scope in _SCOPES:
        handle = k.CreateMutexW(None, False, scope + _NAME)
        if not handle:
            continue                        # 多半是 Global 權限不足，改用 Local
        if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
            k.CloseHandle(handle)
            return None
        _held = Lock(k, handle, scope + _NAME + ".wake")
        if windowed:
            _held.open_door()
        return _held

    _held = Lock(None, None, "")
    return _held


def wake_existing(timeout: float = 1.0) -> bool:
    """通知既有實例把視窗叫回前景，回傳是否敲到。

    敲不到代表對方沒有視窗（命令列的 run），呼叫端要自己說明。
    ⚠ 保留一小段重試：對方可能還在取得鎖與開門之間。
    """
    k = _kernel32()
    if k is None:
        return False
    deadline = time.monotonic() + timeout
    while True:
        for scope in _SCOPES:
            handle = k.OpenEventW(_EVENT_MODIFY_STATE, False,
                                  scope + _NAME + ".wake")
            if not handle:
                continue
            ok = bool(k.SetEvent(handle))
            k.CloseHandle(handle)
            if ok:
                return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.2)
