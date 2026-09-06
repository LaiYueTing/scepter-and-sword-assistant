# -*- coding: utf-8 -*-
"""系統匣圖示的左鍵雙擊還原視窗：

    python tests/test_tray_doubleclick.py

⚠ 這條路沒有實機畫面可驗，selftest 也涵蓋不到（那支是驗規則的），而它壞掉的樣子
  特別安靜：`NotifyIcon` 的 `MouseUp` 帶的 `Clicks` **永遠是 0**（單擊、雙擊都
  一樣），所以 `Clicks == 2` 從來不成立——圖示在、選單也按得動，只有雙擊沒反應，
  紀錄上什麼都看不到。

作法是直接對 `NotifyIcon` 內部那個隱藏視窗送 `WM_TRAYMOUSEMESSAGE`
（`WM_USER + 1024`、lParam 帶真正的滑鼠訊息），那正是通知區域送給它的東西。
"""
import ctypes
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ⚠ 測試不能寫進真正的 assistant.log，要在 import core 之前設定。
os.environ.setdefault("SSA_LOG_DIR", tempfile.mkdtemp(prefix="ssa-test-log-"))

if sys.platform != "win32":
    print("[略過] 系統匣只在 Windows 上有。")
    sys.exit(0)
try:
    import clr  # noqa: F401
except Exception:
    print("[略過] 這個環境沒有 pythonnet，建不出 NotifyIcon。")
    sys.exit(0)

from gui.tray import Tray

WM_TRAY = 0x400 + 1024
WM_LBUTTONDOWN, WM_LBUTTONUP, WM_LBUTTONDBLCLK = 0x201, 0x202, 0x203
WM_RBUTTONDOWN, WM_RBUTTONUP, WM_RBUTTONDBLCLK = 0x204, 0x205, 0x206

ok = True


def check(name: str, passed: bool) -> None:
    global ok
    print(f"  [{'通過' if passed else '失敗'}] {name}")
    ok &= passed


def handle_of(icon) -> int:
    """取 NotifyIcon 內部那個隱藏視窗的 handle。"""
    from System.Reflection import BindingFlags
    from System.Windows.Forms import NotifyIcon

    field = NotifyIcon.GetType(icon).GetField(
        "window", BindingFlags.NonPublic | BindingFlags.Instance
    )
    return int(str(field.GetValue(icon).Handle))


shown = []
tray = Tray(
    None,
    is_running=lambda: False,
    on_show=lambda: shown.append(1),
    on_stop=lambda: None,
    on_quit=lambda: None,
)
tray._create()
hwnd = handle_of(tray._icon)
send = ctypes.windll.user32.SendMessageW


def clicks(*msgs) -> int:
    shown.clear()
    for msg in msgs:
        send(hwnd, WM_TRAY, 1, msg)
    return len(shown)


try:
    print("系統匣的雙擊：")
    # Windows 對通知區域圖示的雙擊實際送的是 DOWN → UP → DBLCLK → UP
    check("左鍵雙擊會叫出視窗",
          clicks(WM_LBUTTONDOWN, WM_LBUTTONUP, WM_LBUTTONDBLCLK, WM_LBUTTONUP) == 1)
    check("而且只叫一次", clicks(
        WM_LBUTTONDOWN, WM_LBUTTONUP, WM_LBUTTONDBLCLK, WM_LBUTTONUP) == 1)
    check("左鍵單擊不動作（那是選取，不是開啟）",
          clicks(WM_LBUTTONDOWN, WM_LBUTTONUP) == 0)
    # 右鍵是叫選單的，連按兩下不該把視窗也開出來
    check("右鍵雙擊不動作",
          clicks(WM_RBUTTONDOWN, WM_RBUTTONUP, WM_RBUTTONDBLCLK, WM_RBUTTONUP) == 0)
finally:
    tray.remove()

print("\n" + ("全部通過" if ok else "有失敗項目"))
sys.exit(0 if ok else 1)
