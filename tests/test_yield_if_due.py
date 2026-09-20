# -*- coding: utf-8 -*-
"""`yield_if_due` 動作：時刻到了就讓位，而且不再執行後面的動作。

    python tests/test_yield_if_due.py

引擎原本只在 `count:` 檢查「排定時刻到了沒」，而副本「未達 S → 退出重打」那條路
不經過 `count`。實測 2026-09-20 煉獄連打 38 場都沒 S，12:30 的討伐被擋到 13:06
才讓位。這支守著：時刻已到 → `yielded` 設起來、後面的動作（按配對）不執行；
時刻未到 → 照常往下做。

不碰模擬器：Device 換成假的，只記錄被點了幾次。
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("SSA_LOG_DIR", tempfile.mkdtemp(prefix="ssa-test-log-"))

import numpy as np

from core.config import Config
from core.engine import Engine, Script

ok = True


def check(name, passed, detail=""):
    global ok
    ok &= bool(passed)
    print(f"  [{'通過' if passed else '失敗'}] {name}" + (f"　{detail}" if detail else ""))


class FakeDevice:
    def __init__(self):
        self.taps = 0
        self.cfg = Config.load(ROOT / "config.example.yaml")

    def tap(self, *a, **k):
        self.taps += 1

    def screencap(self):
        return np.zeros((1280, 720, 3), dtype=np.uint8)


def run_actions(until):
    dev = FakeDevice()
    eng = Engine(dev, Script.load("dungeon", {}))
    eng._until = until
    eng._execute([{"yield_if_due": None}, {"tap": [10, 10]}], dev.screencap(), None)
    return eng, dev


eng, dev = run_actions(datetime.now() - timedelta(seconds=1))
check("時刻已到：讓位記號設起來", eng.yielded and eng._stop)
check("時刻已到：後面的動作不執行", dev.taps == 0, f"點了 {dev.taps} 次")

eng, dev = run_actions(datetime.now() + timedelta(hours=1))
check("時刻未到：不讓位", not eng.yielded and not eng._stop)
check("時刻未到：後面的動作照常", dev.taps == 1, f"點了 {dev.taps} 次")

eng, dev = run_actions(None)
check("沒有 until：照常往下做", not eng.yielded and dev.taps == 1)

rules = Script.load("dungeon", {}).rules
match_rule = next(r for r in rules if r.name == "副本詳情頁 → 確認副本後配對")
verbs = [v for a in match_rule.actions for v in a]
check("副本的配對規則第一個動作就是 yield_if_due", verbs and verbs[0] == "yield_if_due", str(verbs))

print()
print("全部通過" if ok else "有項目失敗")
sys.exit(0 if ok else 1)
