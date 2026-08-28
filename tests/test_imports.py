"""每一個模組都要 import 得起來。直接 `python tests/test_imports.py` 跑。

⚠ **這支守的是「刪掉一個模組之後，還有誰在 import 它」。** 實測踩過一次：
  `gui/protocol.py` 移除之後 `gui/runner.py` 的 `from .protocol import Channel`
  沒改到，而**視窗照樣開得起來**——`runner.py` 要按下「開始執行」才會被載入，
  於是使用者按下去看到的是 `No module named 'gui.protocol'`。

⚠ 用 grep 找漏網之魚是不夠的：漏掉的那一個正是你沒想到的那一個。這支直接把每個
  模組都 import 一次，答案是確定的。

⚠ 這裡只 import，**不執行任何東西**——不連模擬器、不建視窗、不碰設定檔。
"""

from __future__ import annotations

import importlib
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ⚠ **測試不能寫進真正的 assistant.log。** 那是使用者用來監督執行狀況的檔案，
#   混進假的排程與假的下載失敗比沒有紀錄更糟。要在 import core 之前設定。
os.environ.setdefault("SSA_LOG_DIR", tempfile.mkdtemp(prefix="ssa-test-log-"))

FAILED: list[str] = []


def main() -> int:
    print("每個模組都 import 得起來\n")

    mods = sorted(
        f"{d}.{p.stem}"
        for d in ("core", "gui")
        for p in (ROOT / d).glob("*.py")
        if p.stem != "__init__"
    )
    mods += ["core", "gui"]

    for name in sorted(mods):
        try:
            importlib.import_module(name)
        except Exception as e:
            FAILED.append(f"{name}：{type(e).__name__} {e}")
            print(f"  [失敗] {name}　{type(e).__name__}: {e}")
        else:
            print(f"  [通過] {name}")

    print()
    if FAILED:
        print(f"[失敗] {len(FAILED)} 個模組 import 不起來")
        return 1
    print(f"全部通過（{len(mods)} 個模組）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
