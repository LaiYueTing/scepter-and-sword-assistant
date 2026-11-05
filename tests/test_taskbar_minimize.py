"""無邊框主視窗走完「全透明 → 不透明」後，要留著工作列點圖示縮小需要的樣式。

⚠ 要開真的視窗：洗掉樣式的是 WinForms 設定 `Opacity` 的行為，假物件驗不出來。
"""
import ctypes
import os
import pathlib
import sys
import tempfile
import threading
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

# ⚠ 測試不寫進真正的 assistant.log，要在 import core 之前設定。
os.environ.setdefault("SSA_LOG_DIR", tempfile.mkdtemp(prefix="ssa-test-log-"))

import webview

from gui import app

WS_MINIMIZEBOX = 0x00020000
GWL_STYLE = -16
TIMEOUT = 60

user32 = ctypes.windll.user32
user32.GetWindowLongPtrW.restype = ctypes.c_longlong
user32.GetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int]

results: list[tuple[str, bool]] = []


def has_minimize_box(window) -> bool:
    handle = window.native.Handle.ToInt64()
    return bool(user32.GetWindowLongPtrW(handle, GWL_STYLE) & WS_MINIMIZEBOX)


def check(label: str, cond: bool) -> None:
    results.append((label, cond))


# 開在畫面外而且不搶焦點，跑測試時不影響正在操作的視窗。
window = webview.create_window("taskbar minimize test", html="<h1>test</h1>",
                               frameless=True, easy_drag=False, hidden=True,
                               focus=False, x=-3000, y=-3000,
                               width=400, height=300)
loaded = threading.Event()
window.events.loaded += loaded.set


def scenario() -> None:
    try:
        if not loaded.wait(TIMEOUT):
            check("頁面載得起來", False)
            return
        # 順序與 gui/app.py 的 on_loaded → reveal 相同。
        app._show_transparent(window)
        time.sleep(0.5)
        app._show_opaque(window)
        check("顯示主視窗之後有縮小樣式", has_minimize_box(window))

        window.minimize()
        time.sleep(0.5)
        check("縮小之後樣式還在", has_minimize_box(window))

        window.restore()
        time.sleep(0.5)
        check("還原之後樣式還在", has_minimize_box(window))

        window.hide()
        time.sleep(0.5)
        app._restore(window)
        time.sleep(0.5)
        check("從系統匣叫回之後樣式還在", has_minimize_box(window))
    finally:
        window.destroy()


def watchdog() -> None:
    time.sleep(TIMEOUT + 30)
    print("[失敗] 測試逾時")
    os._exit(1)


threading.Thread(target=watchdog, daemon=True).start()
threading.Thread(target=scenario, daemon=True).start()
webview.start()

for label, cond in results:
    print(("[通過] " if cond else "[失敗] ") + label)
sys.exit(0 if results and all(cond for _, cond in results) else 1)
