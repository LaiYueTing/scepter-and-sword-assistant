"""縮到系統匣的通知：關閉後不再跳，視窗仍然要縮起來。"""
import os
import tempfile
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

# ⚠ 測試不寫進真正的 assistant.log，要在 import core 之前設定。
os.environ.setdefault("SSA_LOG_DIR", tempfile.mkdtemp(prefix="ssa-test-log-"))

from core import uistate

ok = True


def check(label, cond):
    global ok
    print(("[通過] " if cond else "[失敗] ") + label)
    ok = ok and bool(cond)


# ⚠ 把 ui.json 指到暫存目錄，不動真正的偏好檔。
_real = uistate.PATH
uistate.PATH = pathlib.Path(tempfile.mkdtemp(prefix="ssa-test-ui-")) / "ui.json"

try:
    # ---------- 預設是會提醒的 ----------
    check("沒設定過時預設要提醒", uistate.get("tray_hint") is True)

    # ---------- 關得掉，而且存得住 ----------
    uistate.set("tray_hint", False)
    check("關掉之後讀回來是 False", uistate.get("tray_hint") is False)
    check("關掉之後真的寫進檔案了", uistate.PATH.is_file())

    # 驗重新載入後仍是 False。
    check("重新載入仍然是 False", uistate.load()["tray_hint"] is False)

    uistate.set("tray_hint", True)
    check("開得回來", uistate.get("tray_hint") is True)

    # ---------- win_hide 要照這個偏好決定跳不跳 ----------
    from gui.api import Api

    class FakeWindow:
        def __init__(self):
            self.hidden = 0

        def hide(self):
            self.hidden += 1

    fired = []
    api = Api.__new__(Api)
    win = FakeWindow()
    api._window = win
    api._on_hidden = lambda: fired.append(1)

    uistate.set("tray_hint", True)
    api.win_hide({})
    check("要提醒時會跳通知", fired == [1])
    check("視窗照樣縮起來", win.hidden == 1)

    uistate.set("tray_hint", False)
    api.win_hide({})
    check("不提醒時不跳通知", fired == [1])
    # 關閉的是通知，視窗仍然要縮起來。
    check("不提醒時視窗仍然要縮起來", win.hidden == 2)

    # ---------- 點通知之後，畫面也要跟著換 ----------
    # 要推事件更新介面上的值。
    from gui.app import TRAY_HINT_TEXT, dismiss_tray_hint

    class FakeChannel:
        def __init__(self):
            self.sent = []

        def send(self, event, data=None):
            self.sent.append((event, data))

    ch = FakeChannel()
    uistate.set("tray_hint", True)
    dismiss_tray_hint(ch)
    check("點通知會關掉偏好", uistate.get("tray_hint") is False)
    check("點通知會推事件給前端",
          ch.sent == [("ui_pref", {"key": "tray_hint", "value": False})])

    # 文字要自己斷行。
    check("通知文字有自己斷行", TRAY_HINT_TEXT.count("\n") == 2)
    check("通知有講「點下去會怎樣」", "不再提醒" in TRAY_HINT_TEXT)

    # ---------- 點通知那條路：處理器只掛一次 ----------
    # 用假的 NotifyIcon 驗。`notify()` 需要 `clr.AddReference`，這裡自己補；沒有 pythonnet 就跳過。
    from gui.tray import Tray

    try:
        import clr

        clr.AddReference("System.Windows.Forms")
    except Exception as e:
        print(f"[跳過] 這個環境沒有 pythonnet，點擊處理器那兩條驗不了：{e}")
        raise SystemExit(0 if ok else 1)

    class FakeEvent:
        """.NET 事件用 `+=` 掛上。"""

        def __init__(self, icon):
            self._icon = icon

        def __iadd__(self, handler):
            self._icon.handlers += 1
            return self

    class FakeIcon:
        def __init__(self):
            self.handlers = 0
            self.shown = 0
            self.BalloonTipClicked = FakeEvent(self)

        def ShowBalloonTip(self, *a):
            self.shown += 1

    tray = Tray.__new__(Tray)
    tray._icon = FakeIcon()
    tray._balloon_click = None
    for _ in range(3):
        tray.notify("測試", on_click=lambda: None)
    check("跳三則通知只掛一個點擊處理器", tray._icon.handlers == 1)
    check("三則都真的跳出去了", tray._icon.shown == 3)
finally:
    uistate.PATH = _real

print()
print("全部通過" if ok else "有項目失敗")
sys.exit(0 if ok else 1)
