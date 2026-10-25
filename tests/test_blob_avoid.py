# -*- coding: utf-8 -*-
"""點了無法互動的門要改點別扇：

    python tests/test_blob_avoid.py

虛空裂縫的地圖上常有別的隊伍正在使用的門，點下去只會跳「玩家無法與該物體進行互動」。
find_blob 一律挑最大的色塊，所以那扇門比較大時會一直點它（實測每 5 秒一次）。
avoid_last_blob 記下上一次點的門，find_blob 跳過它改取次大的；鏡頭一移動就作廢。

用合成的畫面（兩塊紫色），不需要模擬器也不需要樣本。
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ⚠ 測試不能寫進真正的 assistant.log，要在 import core 之前設定。
os.environ.setdefault("SSA_LOG_DIR", tempfile.mkdtemp(prefix="ssa-test-log-"))

import cv2
import numpy as np

from core import vision
from core.engine import Engine

ok = True


def check(name: str, passed: bool, detail: str = "") -> None:
    global ok
    ok &= bool(passed)
    print(f"  [{'通過' if passed else '失敗'}] {name}" + (f"　{detail}" if detail else ""))


def screen() -> np.ndarray:
    """大門在右（60x140）、小門在左（40x80），其餘是灰色。"""
    img = np.full((1280, 720, 3), 120, np.uint8)
    purple = cv2.cvtColor(np.uint8([[[129, 190, 150]]]), cv2.COLOR_HSV2BGR)[0, 0]
    img[540:680, 600:660] = purple
    img[640:720, 190:230] = purple
    return img


SPEC = dict(hue=[120, 140], sat=[150, 255], val=[60, 210], min_area=1500)


class FakeDevice:
    def __init__(self):
        self.taps = []

    def tap(self, x, y):
        self.taps.append((x, y))

    def swipe(self, *args):
        pass


def main() -> int:
    img = screen()
    print("find_blob 的 avoid")
    big = vision.find_blob(img, SPEC)
    check("預設挑最大的（右邊那扇）", big is not None and big.x == 600, str(big))
    small = vision.find_blob(img, SPEC, [big.center])
    check("跳過右邊之後挑左邊那扇", small is not None and small.x == 190, str(small))
    check("兩扇都跳過就是沒有門", vision.find_blob(img, SPEC, [big.center, small.center]) is None)

    print("引擎：tap_match → avoid_last_blob → swipe")
    eng = Engine.__new__(Engine)
    eng.device = FakeDevice()
    eng._blob_avoid, eng._last_blob_tap = [], None
    eng._do("tap_match", [], img, big)
    check("點門之後記住位置", eng._last_blob_tap == big.center, str(eng._last_blob_tap))
    eng._do("avoid_last_blob", 60, img, None)
    check("avoid_last_blob 把它加進要跳過的清單", len(eng._blob_avoid) == 1)
    eng._do("avoid_last_blob", 60, img, None)
    check("同一次點擊不會重複加", len(eng._blob_avoid) == 1)
    eng._do("swipe", [610, 600, 110, 600, 600], img, None)
    check("鏡頭移動之後清單作廢", eng._blob_avoid == [])

    print("\n全部通過。" if ok else "\n有項目未通過。")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
