"""版本號 +1，同時寫進 `assets/version_info.txt` 與 `core/config.py`。

版本號是 X.Y.Z：X 破壞相容（設定檔鍵名、腳本格式）、Y 新功能、Z 修正。

    python tools/bump_version.py            # Z +1
    python tools/bump_version.py --minor    # Y +1，Z 歸零
    python tools/bump_version.py --major    # X +1，其餘歸零

⚠ Windows 的 `filevers` 規定四個數字，固定補 0（1.2.3 → `(1, 2, 3, 0)`）。
⚠ 程式回報的版本來自 `core/config.py` 的 `VERSION`，同步失敗就中止。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = ROOT / "assets" / "version_info.txt"
SOURCE_FILE = ROOT / "core" / "config.py"


def current() -> tuple[int, int, int]:
    """讀 core/config.py 的 VERSION。"""
    m = re.search(r'^VERSION = "(\d+)\.(\d+)\.(\d+)"',
                  SOURCE_FILE.read_text(encoding="utf-8"), re.M)
    if not m:
        raise ValueError(f'{SOURCE_FILE} 裡找不到 VERSION = "X.Y.Z"')
    return tuple(int(g) for g in m.groups())          # type: ignore[return-value]


def bump(part: str) -> str:
    major, minor, patch = current()
    if part == "major":
        major, minor, patch = major + 1, 0, 0
    elif part == "minor":
        minor, patch = minor + 1, 0
    else:
        patch += 1
    return f"{major}.{minor}.{patch}"


def write(dotted: str) -> None:
    tup = ", ".join(dotted.split(".") + ["0"])        # Windows 要四個數字

    text = VERSION_FILE.read_text(encoding="utf-8")
    text = re.sub(r"filevers=\([^)]*\)", f"filevers=({tup})", text)
    text = re.sub(r"prodvers=\([^)]*\)", f"prodvers=({tup})", text)
    for key in ("FileVersion", "ProductVersion"):
        text = re.sub(rf"StringStruct\('{key}', '[^']*'\)",
                      f"StringStruct('{key}', '{dotted}')", text)
    VERSION_FILE.write_text(text, encoding="utf-8", newline="")

    src = SOURCE_FILE.read_text(encoding="utf-8")
    new, n = re.subn(r'^VERSION = "[^"]*"', f'VERSION = "{dotted}"',
                     src, count=1, flags=re.M)
    if not n:
        raise ValueError(f"{SOURCE_FILE} 裡找不到 VERSION，沒有同步版本號")
    SOURCE_FILE.write_text(new, encoding="utf-8", newline="")


def main() -> int:
    ap = argparse.ArgumentParser(description="遞增版本號（X.Y.Z）")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--major", action="store_true", help="X +1，其餘歸零")
    g.add_argument("--minor", action="store_true", help="Y +1，Z 歸零")
    args = ap.parse_args()

    if not VERSION_FILE.is_file():
        print(f"[錯誤] 找不到版本資訊檔：{VERSION_FILE}")
        return 1

    try:
        was = ".".join(str(v) for v in current())
        dotted = bump("major" if args.major else "minor" if args.minor else "patch")
        write(dotted)
    except ValueError as e:
        print(f"[錯誤] {e}")
        return 1

    print(f"[資訊] 版本號 {was} → {dotted}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
