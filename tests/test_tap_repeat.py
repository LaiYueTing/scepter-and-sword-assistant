# -*- coding: utf-8 -*-
"""`tap: [x, y, 次數]` 連點，以及 `top_up` 把組數補到設定值。

    python tests/test_tap_repeat.py

素材祕境的一鍵購買是「讀出今天已買幾組 → 按 − 歸零 → 按 + 補差額」，算錯就是
多買或少買。這支守著：差額算對、已經買夠就不加也不設旗標、讀不到就不買，
以及 OCR 尾巴多一個字（2/201）時仍然取對已買數。

不碰模擬器也不跑 OCR：Device 換成假的，ocr.read 換成固定回傳。
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("SSA_LOG_DIR", tempfile.mkdtemp(prefix="ssa-test-log-"))

import numpy as np

from core import ocr
from core.config import Config
from core.engine import Engine, Script, TOP_UP_CLEAR

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

    def tap_repeat(self, x, y, times):
        self.taps += [(x, y)] * times

    def screencap(self):
        return np.zeros((1280, 720, 3), dtype=np.uint8)


def run(actions, read_text="", options=None):
    ocr.read = lambda *a, **k: read_text
    dev = FakeDevice()
    eng = Engine(dev, Script.load("chores", options or {}))
    eng._execute(actions, dev.screencap(), None)
    return dev.taps, eng._flags


check("沒寫次數：點一下", run([{"tap": [10, 20]}])[0] == [(10, 20)])
check("次數 3：點三下", run([{"tap": [10, 20, 3]}])[0] == [(10, 20)] * 3)
check("次數 0：不點", run([{"tap": [10, 20, 0]}])[0] == [])

opts = {"chores_material": True, "material_hammer_sets": 5, "material_pickaxe_sets": 2}
rules = {r.name: r for r in Script.load("chores", opts).rules}
hammer = rules["一鍵購買：鐵鎚補到設定的組數"].actions
pick = rules["一鍵購買：十字鎬補到設定的組數"].actions
MINUS, PLUS = (472, 445), (593, 445)

taps, flags = run(hammer, "今日限購:0/20|", opts)
check("鐵鎚設 5、今天 0：先歸零再加 5",
      (taps.count(MINUS), taps.count(PLUS)) == (TOP_UP_CLEAR, 5) and taps.index(PLUS) == TOP_UP_CLEAR,
      f"− {taps.count(MINUS)}、+ {taps.count(PLUS)}")
check("要買就設旗標", "素材有要買的" in flags)

taps, flags = run(hammer, "今日限購:3/20|", opts)
check("鐵鎚設 5、今天已買 3：只補 2", taps.count(PLUS) == 2)

taps, flags = run(pick, "今日限購:2/201", opts)
check("十字鎬設 2、已買 2（尾巴多一個 1）：不加、不設旗標",
      taps.count((593, 557)) == 0 and not flags)

taps, flags = run(hammer, "今日限購:12/20", opts)
check("已買兩位數 12：設 5 也不加", taps.count(PLUS) == 0 and not flags)

taps, flags = run(hammer, "", opts)
check("讀不到：只歸零、不加、不設旗標",
      taps.count(MINUS) == TOP_UP_CLEAR and taps.count(PLUS) == 0 and not flags)

glove = rules["一鍵購買：拳套補到設定的組數"].actions
taps, _ = run(glove, "今日限購:0/20", opts)
check("拳套沒設：用預設 2", taps.count((593, 669)) == 2)

buy = rules["一鍵購買：組數調好了 → 購買"]
check("購買要有旗標、一天只按一次", buy.when_flag == ["素材有要買的"] and buy.max_fires_daily == 1)

print()
print("全部通過" if ok else "有項目失敗")
sys.exit(0 if ok else 1)
