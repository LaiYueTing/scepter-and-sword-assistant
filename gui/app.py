"""視窗外殼：建視窗、掛系統匣、把方法表交給 pywebview。

前端是 `gui/ui` 那份 Vue，建置產物在 `gui/web`；用系統內建的 WebView2 引擎，
所以整個程式仍然是單一行程、單一 EXE。

**介面只是另一張臉**——連線、規則引擎、排程全部沿用 `core/` 底下同一份程式，
這裡不重新實作任何判斷邏輯。
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from pathlib import Path

import webview

from core import logger, singleton
from core.config import BUNDLE, VERSION, Config
from core import uistate
from .api import Api
from .bridge import Channel, WebLogHandler
from .tray import Tray

log = logger.get("gui")


def web_dir() -> Path:
    """前端資源的位置。打包後在 BUNDLE（唯讀），開發時在專案裡。"""
    packed = BUNDLE / "gui" / "web"
    return packed if packed.exists() else Path(__file__).parent / "web"


# 「已經在執行中」的說明正開著嗎。系統彈窗是阻塞的，連按好幾次會在關掉一個之後
# 又跳一個；多的那幾次只把視窗叫到前面就好，那本來就是使用者要的。
_explaining = threading.Event()


def _quiet_disposed(record: logging.LogRecord) -> bool:
    """擋掉關視窗那一瞬間的 `ObjectDisposedException`。

    WebView2 被處置之後，還在路上的那一則事件會讓 `evaluate_js` 丟 .NET 例外。
    `Channel._emit` 接得住也只會失敗一次（之後 `_closed` 就擋下來了），但**那個例外是
    pywebview 自己 log 完才吞掉的**——我們的 try/except 根本沒機會碰到它，而 root
    logger 的檔案 handler 收得到所有人的紀錄，於是二十幾行 .NET traceback 一路寫進
    `assistant.log`，把使用者真正要查的東西擠掉。

    ⚠ **要比對的是例外的「型別名稱」，兩個直覺的作法都沒有用：**

      - `record.getMessage()` → pywebview 記的訊息只有「Error occurred in script」，
        一個字都對不上。
      - `str(exc_info[1])` → .NET 例外的字串形式是**本地化過的訊息**
        （「無法存取已處置的物件。」），也沒有那串英文。

      畫面上看到的 `System.ObjectDisposedException:` 是 traceback **格式化時**才補上的
      型別名稱。所以要問 `exc_info[0].__name__`。兩次修錯的症狀完全一樣：
      「明明加了過濾，traceback 還是每次都印」。

    ⚠ 只擋這一種已知的雜訊，pywebview 其他的錯誤照樣留著。
    """
    exc = record.exc_info
    if exc and exc[0] is not None:
        if "ObjectDisposedException" in getattr(exc[0], "__name__", ""):
            return False
    return "ObjectDisposedException" not in record.getMessage()


def _restore(window) -> None:
    """把視窗叫回前景。

    ⚠ **`restore()` 與 `show()` 兩個都要，順序也不能反。** 被縮到系統匣的視窗是
      「隱藏」，被最小化的是「minimized」——只做其中一個，另一種情況就叫不回來。
    """
    try:
        window.restore()
        window.show()
    except Exception as e:
        log.warning("叫回視窗失敗：%s", e)


def _wake(window) -> None:
    """有人又啟動了一次助手：把這個視窗叫回前景並說明原因。

    ⚠ 這是在 singleton 的背景執行緒上跑的。pywebview 的視窗方法會自己 marshal
      回 UI 執行緒，而 MessageBoxW 擋住的也只是這條執行緒。
    """
    _restore(window)

    if _explaining.is_set():
        return
    _explaining.set()
    try:
        # 理由寫在 core/singleton.py，不放進每次都會跳的彈窗裡。
        logger.message_box("杖劍傳說助手",
                           "助手已經在執行中，已切換到原本那個視窗。",
                           logger.MB_INFO)
    finally:
        _explaining.clear()


def main() -> int:
    """開視窗。回傳結束碼，讓 `main.py` 直接拿去 sys.exit。"""
    # 同一時間只能有一個助手在操作模擬器。
    lock = singleton.acquire(windowed=True)
    if lock is None:
        if not singleton.wake_existing():
            logger.message_box("杖劍傳說助手", "已經有一個助手在執行中。",
                               logger.MB_INFO)
        return 0

    channel = Channel()
    api = Api(channel)

    # 紀錄同時進檔案與介面。⚠ 掛在 root logger 上，`core.*` 每個模組都收得到。
    logging.getLogger().addHandler(WebLogHandler(channel))

    # ⚠ **pywebview 的紀錄會落進 assistant.log。** root logger 的檔案 handler 收
    #   得到所有人的紀錄，而關視窗時那串 .NET traceback 有二十幾行——會把使用者
    #   真正要查的東西擠掉。上面 `on_closing` 已經治本（先收通道再拆視窗），
    #   這道濾網是保險：只擋那一種已知的雜訊，pywebview 其他的錯誤照樣留著。
    logging.getLogger("pywebview").addFilter(_quiet_disposed)

    index = web_dir() / "index.html"
    if not index.exists():
        logger.message_box(
            "找不到介面資源",
            f"缺少 {index}\n\n"
            "網頁介面要先建置：\n"
            "  cd gui/ui && npm install && npm run build",
        )
        return 1

    bounds = uistate.get("bounds") or {}
    width = int(bounds.get("width") or 1180)
    height = int(bounds.get("height") or 840)

    # 開在螢幕正中央。
    #
    # ⚠ **pywebview 不給預設位置**，交給作業系統決定——而 WinForms 的預設是
    #   `WindowsDefaultLocation`，也就是每次開都往右下偏一點。使用者的感覺是
    #   「位置隨機」，尤其在關掉又開的時候特別明顯。
    #
    # ⚠ 拿不到螢幕資訊就把 x/y 留成 None（回到系統預設），不要讓外觀問題擋住開窗。
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
        # 自繪標題列。⚠ `easy_drag=False` 是必要的：預設會讓**整個視窗**都能拖，
        #   於是點紀錄面板、拖捲軸都在搬視窗。拖曳區改由 CSS 的
        #   `-webkit-app-region: drag` 指定。
        frameless=True,
        easy_drag=False,
        # ⚠ **`text_select` 預設是 False，而它會往 body 注入一條**
        #   `user-select: none`——於是**整個介面一個字都選不起來**，日誌的
        #   「複製選取的內容」自然按了沒反應（而且那個項目看起來是好的，因為
        #   選單打開時判斷「有沒有選取」得到的答案永遠是「沒有」）。
        #   打開之後改由 `styles/main.css` 決定哪裡選得起來：**預設不給選**
        #   （拖選按鈕與標籤的文字會讓它看起來像網頁），日誌、路徑、輸入框
        #   這些「內容」才開放。
        text_select=True,
        background_color="#16181D",     # 載入前的底色，避免閃一下白畫面
    )
    # ⚠ **視窗一定要走 `attach_window()`（它存進底線開頭的屬性），不能直接掛成
    #   `api.window`。** pywebview 會走訪 js_api 的每一個公開成員，而 window 底下是
    #   .NET 的 Form——屬性鏈無限長，掃到就一路遞迴到 maximum recursion depth，
    #   **每秒刷幾十行錯誤而視窗照樣開得起來**，所以會被誤判成只是雜訊。
    #   我第一次就是想當然耳地寫成 `api.window = window`，理由是「pywebview 只挑
    #   callable」——那是錯的，它掃的是成員不是方法。
    api.attach_window(window)

    def on_loaded() -> None:
        """頁面載好了才接通道，並補一則 `ready`。

        ⚠ **不能在 create_window 之後就 attach。** 那時頁面還沒跑，`window.__recv`
          還不存在——`evaluate_js` 會安靜地什麼都不做，於是開場那幾行紀錄（設定
          說明、「哪些規則因設定而不啟用」）就這樣不見了。接在 `loaded` 上，
          等待期間的訊息會留在 `Channel._pending` 裡，attach 時一次補送。

        ⚠ `ready` 是前端「可以去拉狀態了」的信號。
        """
        channel.attach(window)
        channel.send("ready", {"shell": "web"})

    window.events.loaded += on_loaded

    # 開發用的診斷出口：把一段 JS 丟進頁面跑，結果印到 stderr。
    #
    # ⚠ **只在環境變數存在時才掛**——這是一條可以執行任意程式碼的路。
    #
    # 為什麼值得留著：外觀這一類問題「用看的」判斷不了（顏色到底套上去沒有、
    # 對比夠不夠、某個元素的 computed style 是什麼），而猜錯一次的成本是重編、
    # 重開、再看一眼。
    if os.environ.get("SSA_EVAL"):
        def _eval() -> None:
            """跑一段 JS，把結果印到 stderr。

            ⚠ **`evaluate_js` 不會等 Promise。** 丟一個 async IIFE 進去，拿回來的是
              序列化過的 Promise——也就是 `{}`，而且不會有任何錯誤。要量的東西幾乎
              都需要「點一下、等一下、再讀」，所以約定是：**腳本把結果寫進
              `window.__diag`，這裡輪詢**。同步的腳本則直接用回傳值。
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
            # 固定的標記，呼叫端才 grep 得到——stderr 上還有 pywebview 自己的訊息
            print(f"[EVAL]{text}[/EVAL]", file=sys.stderr, flush=True)

        # 等頁面自己跑完一輪再問，否則量到的是還沒套用外觀的狀態
        window.events.loaded += lambda: threading.Timer(3.0, _eval).start()

    def on_closing() -> bool:
        """視窗被關掉（系統的關閉、Alt+F4）時，不要把正在收尾的腳本一起帶走。

        ⚠ 自繪的 ✕ 走的是 `Api.win_close`，不會經過這裡——那條路要先問使用者。
          這裡接的是「繞過介面的關閉」，所以就地把停止要求送出去。

        ⚠ **通道要在這裡收，不能等 `closed`。** `closed` 是 WebView2 已經被處置
          之後才發的，中間那段每一發 `evaluate_js` 都會丟
          `ObjectDisposedException`——而那是 pywebview **自己 log 完才吞掉**的，
          我們的 `try/except` 根本接不到，例外就一路寫進 assistant.log。
          （第一次我在 `_emit` 裡接、失敗就停，完全沒有用。）
        """
        channel.close()
        if api.is_running():
            api.stop({})
        return True

    window.events.closing += on_closing

    # ---------- 系統匣 ----------
    #
    # ⚠ **排程工具本來就是掛著跑的**，關掉視窗不該等於結束程式。沒有系統匣的話，
    #   「縮到背景」隱藏之後畫面上完全沒有痕跡，右下角也找不到它。
    tray = Tray(
        window,
        is_running=api.is_running,
        on_show=lambda: _restore(window),
        on_stop=lambda: api.stop({}),
        on_quit=lambda: api.win_quit({}),
    )
    tray.install()
    # ⚠ 這一則要說完三件事：**去哪了、還在不在做事、怎麼回來**。少了最後一項，
    #   使用者會再雙擊一次 EXE——而那會被防多開擋下來，看起來就像「按了沒反應」。
    api.set_hidden_hook(
        lambda: tray.notify("已縮到系統匣：排程與腳本繼續執行。雙擊右下角的圖示可以叫回視窗。"))

    # 之後有人再啟動一次，就把這個視窗叫回前景
    lock.listen(lambda: _wake(window))
    webview.start(debug=False)

    # ⚠ **圖示一定要在這裡拆掉。** `Application.Run` 已經結束，沒處置掉的話
    #   Windows 會在通知區域留下一顆幽靈圖示。
    tray.remove()
    channel.close()
    return 0
