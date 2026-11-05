"""系統匣圖示與選單，用 pywebview 已載入的 pythonnet 建立 `NotifyIcon`，不需要額外套件。

⚠ 建不出圖示時回傳 False，程式照常開視窗。
"""

from __future__ import annotations

import sys
import threading
from typing import Callable

from core import logger

log = logger.get("gui")

TITLE = "杖劍傳說助手"


class Tray:
    """系統匣圖示。`on_show` / `on_stop` / `on_quit` 是三個選單動作，由外殼提供。"""

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
        self._stop_item = None      # 「停止執行」選單項目
        self._balloon_click = None  # BalloonTipClicked 的處理器，只掛一次

    # ---------- 建立 ----------

    def install(self) -> bool:
        """掛上系統匣圖示，回傳是否成功。⚠ 要等 `shown`：`NotifyIcon` 要建在有訊息迴圈的主執行緒。"""
        try:
            self._window.events.shown += self._on_shown
            return True
        except Exception as e:                      # pragma: no cover - 環境問題
            log.warning("系統匣掛不上去：%s", e)
            return False

    def _on_shown(self) -> None:
        """視窗顯示後切到 UI 執行緒建立圖示。

        ⚠ 一定要 `Invoke`：在別條執行緒建立的 `NotifyIcon`，選單會按不動。
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
        # 預設項目用粗體：雙擊圖示會做同一件事
        menu.Items[0].Font = _bold(menu.Items[0].Font)

        self._stop_item = menu.Items.Add("停止執行")
        self._stop_item.Click += lambda s, e: self._off_ui(self._on_stop)

        menu.Items.Add(ToolStripSeparator())
        quit_item = menu.Items.Add("結束程式")
        quit_item.Click += lambda s, e: self._off_ui(self._on_quit)

        # 在選單打開時才更新可按狀態。
        menu.Opening += lambda s, e: self._refresh()

        icon = NotifyIcon()
        icon.Icon = _app_icon(Icon, SystemIcons)
        icon.Text = TITLE           # ⚠ 上限 63 字元
        icon.ContextMenuStrip = menu
        icon.Visible = True

        # 左鍵雙擊還原視窗，單擊不動作。
        # ⚠ 用 `MouseDoubleClick`：`MouseUp` 的 `Clicks` 永遠是 0。
        # ⚠ 右鍵雙擊也會進這個事件，所以要判斷按鍵。
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
        """氣泡通知。`on_click` 是點擊通知的回呼。

        ⚠ 只能當捷徑：Windows 11 的 toast 不一定回報 `BalloonTipClicked`。
        """
        if self._icon is None:
            return
        try:
            from System import EventHandler
            from System.Windows.Forms import ToolTipIcon

            if on_click is not None and self._balloon_click is None:
                # 處理器只掛一次，否則點一下會觸發 N 次。
                self._balloon_click = EventHandler(
                    lambda sender, args: self._off_ui(on_click))
                self._icon.BalloonTipClicked += self._balloon_click
            self._icon.ShowBalloonTip(3000, TITLE, text, ToolTipIcon.Info)
        except Exception as e:
            log.warning("系統匣通知失敗：%s", e)

    @staticmethod
    def _off_ui(fn: Callable[[], None]) -> None:
        """把系統匣的動作丟到背景執行緒跑，這裡的每一個回呼都要經過它。

        ⚠ 系統匣事件發生在 UI 執行緒，而 `evaluate_js` 會 Invoke 並阻塞等結果，
          在 UI 執行緒上呼叫會造成死結。
        ⚠ 例外在這裡接住，否則會中斷訊息迴圈。
        """
        def run() -> None:
            try:
                fn()
            except Exception as e:                  # pragma: no cover - 環境問題
                log.warning("系統匣的動作失敗：%s", e)

        threading.Thread(target=run, daemon=True).start()

    def remove(self) -> None:
        """移除圖示。⚠ 要 `Dispose()`，只設 `Visible = False` 會留下幽靈圖示。"""
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
    """通知區域的圖示，從 `sys.executable` 抽取。"""
    try:
        return Icon.ExtractAssociatedIcon(sys.executable)
    except Exception:
        return SystemIcons.Application
