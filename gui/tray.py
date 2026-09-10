"""系統匣圖示與選單。

排程工具本來就是掛著跑的，關掉視窗不該等於結束程式。少了系統匣就沒有「縮到背景」
這條路可走——隱藏之後畫面上完全沒有痕跡，使用者會以為程式不見了。

⚠ **不必多裝任何套件。** pywebview 在 Windows 走的是 winforms 後端，而那條路本來
  就把 pythonnet 拉進來了，所以 `System.Windows.Forms.NotifyIcon` 是現成的。
  用 pystray 會多一個相依、多一份要打包的東西，換來的是一模一樣的功能。

⚠ **有系統匣就一定要有防多開，兩者是配套的。** 執行中關視窗會縮到匣繼續跑，
  使用者以為關掉了、再雙擊一次就有兩個排程同時對同一台模擬器送點擊。
  這一點 `core/singleton.py` 已經顧到了。

⚠ **壞掉要安全退化。** 建不出圖示（非 Windows、pythonnet 沒裝、pywebview 換了後端）
  一律回傳 False，程式照常開視窗——這只是方便，絕不能因為它而讓助手起不來。
"""

from __future__ import annotations

import sys
import threading
from typing import Callable

from core import logger

log = logger.get("gui")

TITLE = "杖劍傳說助手"


class Tray:
    """系統匣圖示。建立、更新、拆除都只從這裡走。

    `on_show` / `on_stop` / `on_quit` 是三個選單動作，由外殼提供——這個模組不認得
    Runner 也不認得 Api，只負責把點擊轉出去。
    """

    def __init__(
        self,
        window,
        *,
        is_running: Callable[[], bool],
        on_show: Callable[[], None],
        on_stop: Callable[[], None],
        on_quit: Callable[[], None],
    ) -> None:
        self._window = window
        self._is_running = is_running
        self._on_show = on_show
        self._on_stop = on_stop
        self._on_quit = on_quit
        self._icon = None           # System.Windows.Forms.NotifyIcon
        self._stop_item = None      # 「停止執行」那一項，要跟著執行狀態開關
        self._balloon_click = None  # BalloonTipClicked 的處理器，只掛一次

    # ---------- 建立 ----------

    def install(self) -> bool:
        """掛上系統匣圖示。回傳有沒有成功。

        ⚠ **要等 `shown` 才做。** `NotifyIcon` 得建在有訊息迴圈的那條執行緒上，
          而那條就是 pywebview 跑 `Application.Run()` 的主執行緒；視窗還沒顯示時
          `window.native` 也還不存在。
        """
        try:
            self._window.events.shown += self._on_shown
            return True
        except Exception as e:                      # pragma: no cover - 環境問題
            log.warning("系統匣掛不上去：%s", e)
            return False

    def _on_shown(self) -> None:
        """視窗出來了：切到 UI 執行緒去建圖示。

        ⚠ **一定要 `Invoke` 過去。** pywebview 的事件處理器不保證跑在 UI 執行緒上，
          而在別條執行緒建出來的 `NotifyIcon` 會有一個沒有訊息迴圈的隱藏視窗——
          圖示畫得出來，**選單卻按不動**，而且不會有任何錯誤訊息。
        """
        try:
            from System import Action

            form = self._window.native
            if form.InvokeRequired:
                form.Invoke(Action(self._create))
            else:
                self._create()
        except Exception as e:                      # pragma: no cover - 環境問題
            log.warning("系統匣建立失敗：%s", e)

    def _create(self) -> None:
        import clr

        clr.AddReference("System.Windows.Forms")
        clr.AddReference("System.Drawing")
        from System.Drawing import Icon, SystemIcons
        from System.Windows.Forms import (
            ContextMenuStrip,
            MouseButtons,
            NotifyIcon,
            ToolStripSeparator,
        )

        menu = ContextMenuStrip()
        show_item = menu.Items.Add("顯示視窗")
        show_item.Click += lambda s, e: self._off_ui(self._on_show)
        # 預設項目要粗體：這是雙擊圖示會做的事，讓兩種操作對得起來
        menu.Items[0].Font = _bold(menu.Items[0].Font)

        self._stop_item = menu.Items.Add("停止執行")
        self._stop_item.Click += lambda s, e: self._off_ui(self._on_stop)

        menu.Items.Add(ToolStripSeparator())
        quit_item = menu.Items.Add("結束程式")
        quit_item.Click += lambda s, e: self._off_ui(self._on_quit)

        # ⚠ 在**選單打開的那一刻**才更新可按狀態，不要另外開一條執行緒去輪詢。
        #   使用者看不到的期間，那個狀態本來就沒有人在乎。
        menu.Opening += lambda s, e: self._refresh()

        icon = NotifyIcon()
        icon.Icon = _app_icon(Icon, SystemIcons)
        icon.Text = TITLE           # ⚠ 這個欄位有 63 字元上限，別塞狀態文字進去
        icon.ContextMenuStrip = menu
        icon.Visible = True

        # 左鍵雙擊還原視窗。單擊不做事：單擊在 Windows 的慣例裡只是選取，
        # 把它接成「開視窗」會在使用者只想看 tooltip 的時候彈出來。
        #
        # ⚠ **一定要用 `MouseDoubleClick`，不能用 `MouseUp` 去判 `Clicks`。**
        #   `NotifyIcon` 的 `MouseUp` 帶的 `Clicks` **永遠是 0**（單擊、雙擊
        #   都一樣），拿它判斷雙擊會完全不觸發，而且不會有任何錯誤訊息。
        # ⚠ **右鍵雙擊也會進這個事件**，所以要判按鍵，否則右鍵連按兩下
        #   會在叫出選單的同時把視窗也開出來。
        def on_double_click(sender, args) -> None:
            if args.Button == MouseButtons.Left:
                self._off_ui(self._on_show)

        icon.MouseDoubleClick += on_double_click
        self._icon = icon

    # ---------- 更新與拆除 ----------

    def _refresh(self) -> None:
        if self._stop_item is None:
            return
        try:
            self._stop_item.Enabled = self._is_running()
        except Exception:
            self._stop_item.Enabled = False

    def notify(self, text: str, on_click: Callable[[], None] | None = None) -> None:
        """氣泡通知。只在視窗看不見的時候才有意義，所以呼叫端要自己判斷。

        `on_click` 是「使用者點了這則通知」的回呼。

        ⚠ **不要把任何功能建在這個事件上。** Windows 11 把氣泡換成了 toast，
          實測一次只收到 `BalloonTipShown` 與 `BalloonTipClosed`，沒有
          `BalloonTipClicked`——而點擊到底會不會回報，取決於使用者是點通知本體、
          點通知中心裡的那則，還是直接關掉。所以它只能當**順手的捷徑**，
          真正可靠的入口是介面設定裡的那個開關。
        """
        if self._icon is None:
            return
        try:
            from System import EventHandler
            from System.Windows.Forms import ToolTipIcon

            if on_click is not None and self._balloon_click is None:
                # 只掛一次：每跳一則就 += 一個處理器的話，點一下會觸發 N 次。
                self._balloon_click = EventHandler(
                    lambda sender, args: self._off_ui(on_click))
                self._icon.BalloonTipClicked += self._balloon_click
            self._icon.ShowBalloonTip(3000, TITLE, text, ToolTipIcon.Info)
        except Exception as e:
            log.warning("系統匣通知失敗：%s", e)

    @staticmethod
    def _off_ui(fn: Callable[[], None]) -> None:
        """把系統匣的動作丟到背景執行緒跑。**這裡的每一個回呼都要走它。**

        ⚠ **在 UI 執行緒上做這些事會把整個程式鎖死。** 系統匣的事件（選單、雙擊、
          通知的點擊）全部是在 pywebview 跑 `Application.Run()` 的那條執行緒上發的，
          而這些動作多半要推事件給前端——那條路是 `evaluate_js`，它
          `Invoke` 之後**阻塞等結果**，而結果的回呼又是排回 UI 執行緒的。
          在 UI 執行緒上呼叫等於自己等自己：訊息迴圈停住，視窗叫不回來、系統匣
          也沒反應，而防多開的鎖還握著，所以連重開一個都不行——只能去工作管理員
          砍掉。實測三條路都會中：結束程式（送 `closing`）、停止執行（送 `status`）、
          點掉那則通知（送 `ui_pref`）。

        ⚠ 例外也要在這裡接住：讓它冒到 .NET 的事件處理器上，會把訊息迴圈一起帶走。
        """
        def run() -> None:
            try:
                fn()
            except Exception as e:                  # pragma: no cover - 環境問題
                log.warning("系統匣的動作失敗：%s", e)

        threading.Thread(target=run, daemon=True).start()

    def remove(self) -> None:
        """拿掉圖示。

        ⚠ **一定要 `Dispose()`，光是 `Visible = False` 不夠。** 沒處置掉的話
          Windows 會在通知區域留下一顆幽靈圖示，要等使用者把滑鼠掃過去才消失。
        """
        if self._icon is None:
            return
        try:
            self._icon.Visible = False
            self._icon.Dispose()
        except Exception:
            pass
        self._icon = None


def _bold(font):
    from System.Drawing import FontStyle
    from System.Drawing import Font

    return Font(font, FontStyle.Bold)


def _app_icon(Icon, SystemIcons):
    """通知區域要用的圖示。

    打包之後 `sys.executable` 就是助手自己的 EXE，抽出來的正是它的圖示——所以
    **不必多打包一個 .ico**，也不會有「圖示檔忘了跟著更新」的問題。從原始碼執行時
    抽到的是 python.exe 的圖示，那只影響開發時的觀感。
    """
    try:
        return Icon.ExtractAssociatedIcon(sys.executable)
    except Exception:
        return SystemIcons.Application
