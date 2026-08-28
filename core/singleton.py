"""單一實例：同一時間只允許一個助手在操作模擬器。

擋的不是「視窗開了兩個」，是**兩個排程同時對同一台模擬器送點擊**。引擎是看畫面
決定動作的，另一個行程換掉畫面就會讓它把上一輪記下的座標點在別的頁面上，而代價
落在每天只有兩次的討伐與領獎上。設定檔（讀整份、改一行、寫回）與紀錄檔的 2MB
輪替同樣禁不起兩個行程。

鎖是一個具名 mutex，「把既有視窗叫回來」走一個具名 event，兩者都是 kernel 物件：
不開連接埠、不必靠視窗標題找人，兩種圖形介面與命令列共用同一把。

    lock = singleton.acquire(windowed=True)
    if lock is None:                      # 已經有一個在跑
        singleton.wake_existing()         # 把那個視窗叫回前景
        return 0
    lock.listen(叫回自己視窗的函式)        # 視窗建好之後接上

⚠ `windowed` 要在**取得鎖的當下**就講明，不能等視窗建好才掛門。連續雙擊兩次
  時第一個行程還在載入介面（要好幾秒），那段期間門沒掛上的話，第二個
  行程會敲不到而誤判成「那一個沒有視窗」，跳出一則說錯原因、而且要人按確定才
  關得掉的彈窗。門先開著，敲門先記著，回呼補上時再補叫一次。

⚠ 名稱刻意**不分開發版與打包版**。「拿 python main.py 測試時 dist 的 EXE 正在跑」
  正是要擋的情況之一——兩邊操作的是同一台模擬器。

⚠ 只掛在「會操作裝置」的執行上（兩種介面與 run）。doctor、explain、find、selftest
  都是唯讀工具，擋了只會妨礙除錯。
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

# 先試 Global 再退 Local：工作排程器設成「不論使用者是否登入」時跑在 session 0，
# 而視窗在使用者的 session——只有 Global 命名空間看得到彼此。
_SCOPES = ("Global\\", "Local\\")

_ERROR_ALREADY_EXISTS = 183
_EVENT_MODIFY_STATE = 0x0002
_WAIT_OBJECT_0 = 0
_INFINITE = 0xFFFFFFFF

_held: "Lock | None" = None


def _kernel32():
    """拿到 kernel32，非 Windows 或載入失敗時回傳 None（那時一律不擋）。"""
    if not sys.platform.startswith("win"):
        return None
    try:
        k = ctypes.WinDLL("kernel32", use_last_error=True)
    except (AttributeError, OSError):
        return None

    # ⚠ 一定要宣告 restype。預設是 int，64 位下的 handle 會被截掉高位元，
    #   之後拿去 SetEvent / CloseHandle 就指到別的東西上了。
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
    """握在手上的那把鎖。

    ⚠ 呼叫端要一直保留參考——這個物件被回收就等於解鎖。模組層級的 `_held` 已經
      幫忙留了一份，所以實務上不會，但別依賴那個細節。
    """

    def __init__(self, k, mutex, wake_name: str) -> None:
        self._k = k
        self._mutex = mutex
        self._wake_name = wake_name
        self._wake = None
        self._on_wake: Callable[[], None] | None = None
        self._knocked = False               # 回呼還沒接上時先記著
        self._guard = threading.Lock()

    def open_door(self) -> None:
        """開始接受「把視窗叫回來」的敲門。冪等。

        ⚠ 這要在**取得鎖的當下**做，不能等視窗建好——理由見模組開頭。回呼還沒
          接上的那段時間，敲門先記在 `_knocked` 裡，`listen()` 會補叫一次。

        ⚠ 命令列的 run 不開門（`acquire()` 的 windowed 預設是 False）：它沒有
          視窗可叫，第二個實例要敲不到才知道該自己說明。這是分工，不是漏掉。
        """
        if self._k is None or self._wake is not None or not self._wake_name:
            return
        # 自動重設（第二個參數 False）：敲一次醒一次，不必自己清狀態
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
                except Exception as e:      # 介面掛掉不該把腳本一起帶走
                    log.warning("叫回視窗失敗：%s", e)

        threading.Thread(target=loop, daemon=True).start()

    def listen(self, on_wake: Callable[[], None]) -> None:
        """視窗建好之後把回呼接上，每敲一次門就呼叫 on_wake 一次。

        ⚠ on_wake 是在**等門的那條背景執行緒**上呼叫的。要碰介面就得自己切回
          主執行緒（pywebview 的視窗方法會自己 marshal）。

        ⚠ 只有一個例外：接上之前就敲過門的話，那一次是在**呼叫 listen 的這條
          執行緒**上補叫的。別為此放寬上面那條——兩種情況共用同一個回呼。
        """
        with self._guard:
            self._on_wake = on_wake
            pending, self._knocked = self._knocked, False
        if pending:
            on_wake()

    def release(self) -> None:
        """放掉鎖。行程結束時系統本來就會收回，這是給測試與明確收尾用的。"""
        global _held
        for handle in (self._wake, self._mutex):
            if handle and self._k is not None:
                self._k.CloseHandle(handle)
        self._wake = self._mutex = None
        if _held is self:
            _held = None


def acquire(windowed: bool = False) -> Lock | None:
    """取得鎖；已經有別的行程握著就回傳 None。

    `windowed` 表示「我等一下會有視窗可以叫回前景」，兩種圖形介面都要帶。門在
    這一刻就開，不等視窗建好——理由見模組開頭。

    ⚠ 同一個行程重複呼叫會拿到**同一把**，不會自己擋自己——`main.py` 與
      `gui/app.py` 兩層都會呼叫（前者是為了在載入介面之前就擋下來）。
    """
    global _held
    if _held is not None:
        if windowed:
            _held.open_door()
        return _held

    k = _kernel32()
    if k is None:
        _held = Lock(None, None, "")        # 擋不了就不擋，不要因此不能啟動
        return _held

    for scope in _SCOPES:
        handle = k.CreateMutexW(None, False, scope + _NAME)
        if not handle:
            continue                        # 多半是 Global 的權限不足，退 Local
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
    """敲既有實例一下，把它的視窗叫回前景。回傳有沒有敲到。

    敲不到的情況是**那一個沒有視窗**（命令列的 run，或工作排程器跑的那一份），
    這時呼叫端要自己說明——否則使用者雙擊之後什麼都沒發生，看起來像壞了。

    ⚠ 仍留一小段重試：對方可能正卡在「拿到鎖」與「開門」之間那幾行。門本身是
      在取得鎖的當下就開的（不是等視窗建好），所以這裡不必等對方把介面載完。
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
