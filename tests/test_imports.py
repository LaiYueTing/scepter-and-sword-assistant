"""每一個模組都要 import 得起來。直接 `python tests/test_imports.py` 跑。

涵蓋延後載入的模組（`gui/runner.py` 按下「開始執行」才載入）。只 import，不執行。
"""

from __future__ import annotations

import importlib
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ⚠ 測試不寫進真正的 assistant.log，要在 import core 之前設定。
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
