"""視窗外殼：建視窗、掛系統匣、把方法表交給 pywebview。

前端是 `gui/ui` 的 Vue，建置產物在 `gui/web`，用系統內建的 WebView2 引擎。不實作任何判斷邏輯。
"""

from __future__ import annotations

import ctypes
import json
import logging
import os
import sys
import threading
import time
from pathlib import Path

import webview

from core import logger, singleton, splash
from core.config import BUNDLE, VERSION, Config
from core import uistate
from .api import Api
from .bridge import Channel, WebLogHandler
from .tray import Tray

log = logger.get("gui")

# 等不到前端回報畫好時，強制顯示主視窗（秒）
REVEAL_TIMEOUT = 20


def web_dir() -> Path:
    """前端資源的位置：打包後在 BUNDLE，開發時在專案裡。"""
    packed = BUNDLE / "gui" / "web"
    return packed if packed.exists() else Path(__file__).parent / "web"


# 「已經在執行中」的對話框是否開著。系統對話框是阻塞的，開著時不再跳第二個。
_explaining = threading.Event()


def _quiet_disposed(record: logging.LogRecord) -> bool:
    """過濾 pywebview 的兩種已知雜訊，其他錯誤照常留著：

    關閉視窗瞬間的 `ObjectDisposedException`，以及結束時的「Failed to delete user data folder」。

    ⚠ 比對例外的型別名稱（`exc_info[0].__name__`）：訊息只有「Error occurred in script」，
      `str(exc_info[1])` 是本地化過的文字。
    """
    exc = record.exc_info
    if exc and exc[0] is not None:
        if "ObjectDisposedException" in getattr(exc[0], "__name__", ""):
            return False
    message = record.getMessage()
    return ("ObjectDisposedException" not in message
            and "Failed to delete user data folder" not in message)


def _allow_taskbar_minimize(window) -> None:
    """補上 `WS_MINIMIZEBOX`，讓點工作列圖示可以縮小視窗。

    無邊框視窗（FormBorderStyle.None）沒有這個樣式位元，WinForms 也不理會 `MinimizeBox`。

    ⚠ 要等 handle 建好（接在 `shown` 上）。
    """
    try:
        handle = window.native.Handle.ToInt64()
        user32 = ctypes.windll.user32
        user32.GetWindowLongPtrW.restype = ctypes.c_longlong
        user32.GetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int]
        user32.SetWindowLongPtrW.restype = ctypes.c_longlong
        user32.SetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                             ctypes.c_longlong]
        gwl_style, ws_minimizebox = -16, 0x00020000
        style = user32.GetWindowLongPtrW(handle, gwl_style)
        user32.SetWindowLongPtrW(handle, gwl_style, style | ws_minimizebox)
    except Exception as e:
        log.warning("補不上視窗的縮小樣式，工作列點圖示不會縮小：%s", e)


def _set_opacity(window, value: float) -> None:
    """設定視窗不透明度。⚠ 失敗時不可往上拋：呼叫端接著要關閉啟動畫面。"""
    try:
        from System import Action
        form = window.native

        def apply() -> None:
            form.Opacity = value

        form.Invoke(Action(apply))
    except Exception as e:
        log.warning("無法設定視窗的不透明度：%s", e)


def _restore(window) -> None:
    """把視窗叫回前景。⚠ `restore()` 與 `show()` 都要，順序不可反（最小化與隱藏是兩種狀態）。"""
    try:
        window.restore()
        window.show()
    except Exception as e:
        log.warning("叫回視窗失敗：%s", e)


def _wake(window) -> None:
    """另一個行程要求叫回視窗：叫回前景並說明原因。⚠ 跑在 singleton 的背景執行緒上。"""
    _restore(window)

    if _explaining.is_set():
        return
    _explaining.set()
    try:
        logger.message_box("杖劍傳說助手",
                           "助手已經在執行中，已切換到原本那個視窗。",
                           logger.MB_INFO)
    finally:
        _explaining.clear()


# 縮到系統匣時的通知：去哪了、還在不在執行、怎麼回來，以及點擊通知的效果。
# ⚠ 要自己斷行（`\n` 在 Windows 11 的 toast 上有效）。
TRAY_HINT_TEXT = ("已縮到系統匣，排程與腳本繼續執行。\n"
                  "雙擊右下角的圖示可以叫回視窗。\n"
                  "（點擊這則通知將不再提醒）")


def dismiss_tray_hint(channel) -> None:
    """使用者點了通知：不再提醒。⚠ 要推事件更新介面上的設定值，只寫檔案畫面不會變。"""
    uistate.set("tray_hint", False)
    channel.send("ui_pref", {"key": "tray_hint", "value": False})


def main() -> int:
    """開視窗，回傳結束碼。"""
    # 同一時間只能有一個助手操作模擬器。
    lock = singleton.acquire(windowed=True)
    if lock is None:
        splash.close()
        if not singleton.wake_existing():
            logger.message_box("杖劍傳說助手", "已經有一個助手在執行中。",
                               logger.MB_INFO)
        return 0

    channel = Channel()
    api = Api(channel)

    # 紀錄同時進檔案與介面。掛在 root logger 上。
    logging.getLogger().addHandler(WebLogHandler(channel))

    # 過濾 pywebview 寫進 assistant.log 的已知雜訊。
    logging.getLogger("pywebview").addFilter(_quiet_disposed)

    index = web_dir() / "index.html"
    if not index.exists():
        splash.close()
        logger.message_box(
            "找不到介面資源",
            f"缺少 {index}\n\n"
            "網頁介面要先建置：\n"
            "  cd gui/ui && npm install && npm run build",
        )
        return 1

    splash.step("建立視窗")
    bounds = uistate.get("bounds") or {}
    width = int(bounds.get("width") or 1180)
    height = int(bounds.get("height") or 840)

    # 開在螢幕正中央（pywebview 預設交給系統，每次位置不同）。拿不到螢幕資訊時交給系統。
    pos = {}
    try:
        screen = webview.screens[0]
        pos = {"x": max(0, (screen.width - width) // 2),
               "y": max(0, (screen.height - height) // 2)}
    except Exception as e:
        log.debug("算不出置中位置，交給系統決定：%s", e)

    window = webview.create_window(
        f"杖劍傳說助手 {VERSION}",
        url=str(index),
        js_api=api,
        width=width,
        height=height,
        min_size=(940, 640),
        **pos,
        # 自繪標題列。⚠ `easy_drag=False`：預設整個視窗都能拖，拖曳區由 CSS 指定。
        frameless=True,
        easy_drag=False,
        # ⚠ `text_select=True`：預設會在 body 注入 user-select: none。
        #   可選取的範圍由 `styles/main.css` 決定。
        text_select=True,
        background_color="#16181D",     # 載入前的底色
        # 前端畫好才顯示（`reveal`）。視窗一建立就顯示的話，會有約 1.4 秒的空白並蓋住啟動畫面。
        hidden=True,
    )
    # ⚠ 視窗走 `attach_window()`，不可掛成 `api.window`（見 Api.attach_window）。
    api.attach_window(window)

    reveal_once = threading.Lock()

    def reveal() -> None:
        """前端畫好：主視窗切成不透明，關閉啟動畫面。只執行一次。"""
        if not reveal_once.acquire(blocking=False):
            return
        reveal_fallback.cancel()
        window.show()
        _set_opacity(window, 1)
        splash.close()

    # ⚠ WebView2 載入失敗時不會有回報，少了這個保險，程式會在背景執行而看不到任何畫面。
    reveal_fallback = threading.Timer(REVEAL_TIMEOUT, reveal)
    reveal_fallback.daemon = True
    api.set_painted_hook(reveal)

    def on_loaded() -> None:
        """頁面載好才接通道並送 `ready`。

        ⚠ 不可在 create_window 之後就接：`window.__recv` 還不存在，evaluate_js 不會報錯也不會執行。
          等待期間的訊息留在 `Channel._pending`。
        ⚠ 直接從隱藏切成顯示會有約 0.4 秒空白，所以先以全透明顯示，由前端畫好後回報（`Api.ui_painted`）。
        """
        channel.attach(window)
        channel.send("ready", {"shell": "web"})
        splash.step("完成")
        if not reveal_once.locked():
            _set_opacity(window, 0)
            window.show()

    def on_shown() -> None:
        splash.step("載入畫面")
        _allow_taskbar_minimize(window)

    window.events.loaded += on_loaded
    window.events.shown += on_shown

    # 開發用的診斷出口：把一段 JS 丟進頁面執行，結果印到 stderr。
    # ⚠ 只在環境變數 SSA_EVAL 存在時才掛，這條路可以執行任意程式碼。
    if os.environ.get("SSA_EVAL"):
        def _eval() -> None:
            """執行一段 JS，把結果印到 stderr。

            ⚠ `evaluate_js` 不等 Promise。非同步腳本把結果寫進 `window.__diag`，這裡輪詢。
            """
            try:
                out = window.evaluate_js(os.environ["SSA_EVAL"])
                for _ in range(40):          # 最多等 20 秒
                    got = window.evaluate_js("window.__diag ?? null")
                    if got is not None:
                        out = got
                        break
                    time.sleep(0.5)
                text = json.dumps(out, ensure_ascii=False)
            except Exception as e:
                text = f"error {e}"
            # 固定的標記，呼叫端用來搜尋
            print(f"[EVAL]{text}[/EVAL]", file=sys.stderr, flush=True)

        # 等頁面穩定再執行
        window.events.loaded += lambda: threading.Timer(3.0, _eval).start()

    def on_closing() -> bool:
        """視窗被系統關閉（Alt+F4）時送出停止要求，結束程序在背景跑完。

        自繪的 ✕ 走 `Api.win_close`，不經過這裡。

        ⚠ 通道要在這裡關閉，不可等 `closed`：那時 WebView2 已處置，
          ObjectDisposedException 由 pywebview 自己寫進紀錄，接不到。
        """
        channel.close()
        if api.is_running():
            api.stop({})
        return True

    window.events.closing += on_closing

    # ---------- 系統匣 ----------
    tray = Tray(
        window,
        is_running=api.is_running,
        on_show=lambda: _restore(window),
        on_stop=lambda: api.stop({}),
        on_quit=lambda: api.win_quit({}),
    )
    tray.install()
    # 通知內容見 TRAY_HINT_TEXT。點擊通知不一定收得到事件（見 `Tray.notify`），
    # 所以「介面設定」裡也有同一個開關。
    api.set_hidden_hook(
        lambda: tray.notify(TRAY_HINT_TEXT,
                            on_click=lambda: dismiss_tray_hint(channel)))

    # 之後有人再啟動一次，把這個視窗叫回前景
    lock.listen(lambda: _wake(window))
    reveal_fallback.start()
    webview.start(debug=False)

    # ⚠ 要在這裡移除圖示，否則通知區域會留下一顆幽靈圖示。
    tray.remove()
    channel.close()
    return 0
