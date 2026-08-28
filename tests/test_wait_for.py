# -*- coding: utf-8 -*-
"""`wait_for` 動作的回歸測試：

    python tests/test_wait_for.py

這條路 selftest 驗不到——那支是一張畫面判一次規則，而 `wait_for` 只出現在
`on_finish`（無條件執行的清單，沒有規則會經過它）。要守住的是三件事：
**看到就立刻往下走**、**看不到會等而不是直接跳過**、**逾時要放行不要卡住收尾**。
"""
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ⚠ **測試不能寫進真正的 assistant.log。** 那是使用者用來監督執行狀況的檔案，
#   混進假的排程與假的下載失敗比沒有紀錄更糟。要在 import core 之前設定。
os.environ.setdefault("SSA_LOG_DIR", tempfile.mkdtemp(prefix="ssa-test-log-"))

import numpy as np

from core import engine as eng
from core import vision
from core.config import Config
from core.engine import Engine

ok = True


def check(name: str, passed: bool) -> None:
    global ok
    print(f"  [{'通過' if passed else '失敗'}] {name}")
    ok &= passed


class FakeDevice:
    """回傳指定畫面的假裝置。`hit_after` 秒之後才換成「看得到」的那張。"""

    def __init__(self, hit_after: float):
        self.hit_after = hit_after
        self.start = time.time()
        self.shots = 0

    def screencap(self) -> np.ndarray:
        self.shots += 1
        return np.zeros((1280, 720, 3), np.uint8)


def make_engine(dev, seen_after: float):
    cfg = Config.load(ROOT / "dist" / "config.yaml")
    e = Engine.__new__(Engine)
    e.device, e.cfg, e._finishing = dev, cfg, True
    e._stop_event = __import__("threading").Event()
    # 用假的 exists 決定「畫面上看不看得到」，不必真的準備兩張圖
    started = time.time()
    vision.exists = lambda *a, **k: time.time() - started >= seen_after
    return e


_real_exists = vision.exists
try:
    print("=== 1. 看得到就立刻往下走 ===")
    d = FakeDevice(0)
    e = make_engine(d, seen_after=0)
    t0 = time.time()
    e._do("wait_for", ["nav_home"], None, None)
    check("沒有多等", time.time() - t0 < 1.0)
    check("有抓過畫面", d.shots >= 1)

    print("=== 2. 看不到就等，出現了才往下走 ===")
    d = FakeDevice(0)
    e = make_engine(d, seen_after=1.5)
    t0 = time.time()
    e._do("wait_for", "nav_home", None, None)
    waited = time.time() - t0
    check(f"等到它出現才返回（{waited:.1f} 秒）", 1.3 <= waited <= 3.0)

    print("=== 3. 逾時要放行，不能把收尾卡住 ===")
    old_timeout = eng.WAIT_FOR_TIMEOUT
    eng.WAIT_FOR_TIMEOUT = 1.5
    try:
        d = FakeDevice(0)
        e = make_engine(d, seen_after=9999)
        t0 = time.time()
        e._do("wait_for", ["nav_home", "btn_back_arrow"], None, None)
        waited = time.time() - t0
        check(f"逾時就返回（{waited:.1f} 秒）", 1.3 <= waited <= 3.5)
    finally:
        eng.WAIT_FOR_TIMEOUT = old_timeout
finally:
    vision.exists = _real_exists

print("\n" + ("全部通過" if ok else "有失敗項目"))
sys.exit(0 if ok else 1)
