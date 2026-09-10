"""縮到系統匣的那則通知：關掉之後就不能再跳，而且只能關這一次。

這條路 selftest 驗不到（那支是驗規則的），而壞掉的樣子很安靜——不是「跳錯」
就是「再也不跳」，兩種都沒有錯誤訊息。
"""
import os
import tempfile
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

# ⚠ 測試不能寫進真正的 assistant.log，要在 import core 之前設定。
os.environ.setdefault("SSA_LOG_DIR", tempfile.mkdtemp(prefix="ssa-test-log-"))

from core import uistate

ok = True


def check(label, cond):
    global ok
    print(("[通過] " if cond else "[失敗] ") + label)
    ok = ok and bool(cond)


# ⚠ `ui.json` 在專案旁邊，是使用者真正的偏好檔——測試改到它的話，他的主題與
#   視窗大小會被這支測試洗掉。指到暫存目錄再跑。
_real = uistate.PATH
uistate.PATH = pathlib.Path(tempfile.mkdtemp(prefix="ssa-test-ui-")) / "ui.json"

try:
    # ---------- 預設是會提醒的 ----------
    check("沒設定過時預設要提醒", uistate.get("tray_hint") is True)

    # ---------- 關得掉，而且存得住 ----------
    uistate.set("tray_hint", False)
    check("關掉之後讀回來是 False", uistate.get("tray_hint") is False)
    check("關掉之後真的寫進檔案了", uistate.PATH.is_file())

    # ⚠ 布林值最容易被 `值 || 預設` 那種寫法推回 True，所以要驗「重新載入」。
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
    # ⚠ 關掉的是「通知」，不是「縮到系統匣」。少了這一條，把兩件事寫在一起的
    #   實作也會通過上面那條。
    check("不提醒時視窗仍然要縮起來", win.hidden == 2)

    # ---------- 點通知之後，畫面也要跟著換 ----------
    # ⚠ 只寫 ui.json 的話，「介面設定」那一列會停在「提醒」直到下次啟動——
    #   使用者回報過，而那看起來就像「點了沒有記住」。
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

    # ⚠ 一整串跑完會在 toast 上擠成一團，而換行字元實測是有效的（三行都畫得出來）。
    check("通知文字有自己斷行", TRAY_HINT_TEXT.count("\n") == 2)
    check("通知有講「點下去會怎樣」", "不再提醒" in TRAY_HINT_TEXT)

    # ---------- 點通知那條路：處理器只掛一次 ----------
    # ⚠ 每跳一則就 `+=` 一個處理器的話，點一下會觸發 N 次——而那條路是寫檔案，
    #   看不出重複。這裡用假的 NotifyIcon 驗，真的那顆要 UI 執行緒才建得起來。
    #
    # ⚠ `notify()` 裡的 `from System import EventHandler` 靠 `_create()` 先做過
    #   `clr.AddReference`——真實流程一定是那個順序（圖示沒建起來就直接 return），
    #   而這裡跳過了它，所以要自己補。沒有 pythonnet 的環境就跳過這兩條。
    from gui.tray import Tray

    try:
        import clr

        clr.AddReference("System.Windows.Forms")
    except Exception as e:
        print(f"[跳過] 這個環境沒有 pythonnet，點擊處理器那兩條驗不了：{e}")
        raise SystemExit(0 if ok else 1)

    class FakeEvent:
        """.NET 的事件是用 `+=` 掛的，所以假物件也要吃得下那個寫法。"""

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
