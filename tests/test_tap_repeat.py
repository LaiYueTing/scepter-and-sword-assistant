# -*- coding: utf-8 -*-
"""`tap: [x, y, 次數]` 連點，以及素材祕境的組數照設定點。

    python tests/test_tap_repeat.py

一鍵購買的組數是「先按 − 歸零、再按 + 設定的次數」，點錯次數就是多買或少買。
這支守著：第三個數字就是點幾下、0 不點、沒寫就點一下，以及腳本裡的
`${material_*_sets:2}` 真的換成設定檔的值。

不碰模擬器：Device 換成假的，只記錄點了哪裡。
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("SSA_LOG_DIR", tempfile.mkdtemp(prefix="ssa-test-log-"))

import numpy as np

import core.engine as engine_mod
from core.config import Config
from core.engine import Engine, Script

engine_mod.TAP_REPEAT_GAP = 0           # 測試不必真的等

ok = True


def check(name, passed, detail=""):
    global ok
    ok &= bool(passed)
    print(f"  [{'通過' if passed else '失敗'}] {name}" + (f"　{detail}" if detail else ""))


class FakeDevice:
    def __init__(self):
        self.taps = []
        self.cfg = Config.load(ROOT / "config.example.yaml")

    def tap(self, x, y, *a, **k):
        self.taps.append((x, y))

    def screencap(self):
        return np.zeros((1280, 720, 3), dtype=np.uint8)


def taps_of(actions, options=None):
    dev = FakeDevice()
    eng = Engine(dev, Script.load("chores", options or {}))
    eng._execute(actions, dev.screencap(), None)
    return dev.taps


check("沒寫次數：點一下", taps_of([{"tap": [10, 20]}]) == [(10, 20)])
check("次數 3：點三下", taps_of([{"tap": [10, 20, 3]}]) == [(10, 20)] * 3)
check("次數 0：不點", taps_of([{"tap": [10, 20, 0]}]) == [])

opts = {"chores_material": True, "material_hammer_sets": 5, "material_pickaxe_sets": 0}
rules = {r.name: r for r in Script.load("chores", opts).rules}

hammer = rules["一鍵購買：鐵鎚今天還沒買 → 調成設定的組數"]
taps = taps_of(hammer.actions, opts)
minus, plus = taps.count((472, 445)), taps.count((593, 445))
check("鐵鎚設 5：先按 − 25 下歸零，再按 + 5 下", (minus, plus) == (25, 5), f"− {minus}、+ {plus}")
check("歸零排在加之前", taps.index((593, 445)) > 24)

pick = rules["一鍵購買：十字鎬今天還沒買 → 調成設定的組數"]
taps = taps_of(pick.actions, opts)
check("十字鎬設 0：只歸零不加", taps.count((593, 557)) == 0 and taps.count((472, 557)) == 25)

glove = rules["一鍵購買：拳套今天還沒買 → 調成設定的組數"]
taps = taps_of(glove.actions, opts)
check("拳套沒設：用預設 2", taps.count((593, 669)) == 2, f"+ {taps.count((593, 669))}")

buy = rules["一鍵購買：組數調好了 → 購買"]
check("購買一天只按一次（跨執行保留）", buy.max_fires_daily == 1)

print()
print("全部通過" if ok else "有項目失敗")
sys.exit(0 if ok else 1)
