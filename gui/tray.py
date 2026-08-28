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
        show_item.Click += lambda s, e: self._on_show()
        # 預設項目要粗體：這是雙擊圖示會做的事，讓兩種操作對得起來
        menu.Items[0].Font = _bold(menu.Items[0].Font)

        self._stop_item = menu.Items.Add("停止執行")
        self._stop_item.Click += lambda s, e: self._on_stop()

        menu.Items.Add(ToolStripSeparator())
        quit_item = menu.Items.Add("結束程式")
        quit_item.Click += lambda s, e: self._on_quit()

        # ⚠ 在**選單打開的那一刻**才更新可按狀態，不要另外開一條執行緒去輪詢。
        #   使用者看不到的期間，那個狀態本來就沒有人在乎。
        menu.Opening += lambda s, e: self._refresh()

        icon = NotifyIcon()
        icon.Icon = _app_icon(Icon, SystemIcons)
        icon.Text = TITLE           # ⚠ 這個欄位有 63 字元上限，別塞狀態文字進去
        icon.ContextMenuStrip = menu
        icon.Visible = True

        # 雙擊還原。單擊不做事——單擊在 Windows 的慣例裡只是選取，
        # 把它接成「開視窗」會在使用者只想看 tooltip 的時候彈出來。
        def on_click(sender, args) -> None:
            if args.Button == MouseButtons.Left and args.Clicks == 2:
                self._on_show()

        icon.MouseUp += on_click
        self._icon = icon

    # ---------- 更新與拆除 ----------

    def _refresh(self) -> None:
        if self._stop_item is None:
            return
        try:
            self._stop_item.Enabled = self._is_running()
        except Exception:
            self._stop_item.Enabled = False

    def notify(self, text: str) -> None:
        """氣泡通知。只在視窗看不見的時候才有意義，所以呼叫端要自己判斷。"""
        if self._icon is None:
            return
        try:
            from System.Windows.Forms import ToolTipIcon

            self._icon.ShowBalloonTip(3000, TITLE, text, ToolTipIcon.Info)
        except Exception as e:
            log.warning("系統匣通知失敗：%s", e)

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
