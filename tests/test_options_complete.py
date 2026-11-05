"""玩法設定要列出全部選項（`_options_json` 用範本補舊設定檔缺少的鍵）：

  1. 每一個開關都出現在介面上（即使設定檔一個都沒有）
  2. 沒有鍵歸到「其他」分頁
  3. 範本的預設值和腳本的 `${鍵:預設}` 一致

    python tests/test_options_complete.py
"""

from __future__ import annotations

import re
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ⚠ 測試不寫進真正的 assistant.log，要在 import core 之前設定。
os.environ.setdefault("SSA_LOG_DIR", tempfile.mkdtemp(prefix="ssa-test-log-"))

import yaml

from core import optionmeta
from core.config import Config, resource_files, resource_file
from gui.api import Api

failures: list[str] = []


def check(ok: bool, name: str, detail: str = "") -> None:
    print(f"  [{'通過' if ok else '失敗'}] {name}" + (f"　{detail}" if detail else ""))
    if not ok:
        failures.append(name)


def main() -> int:
    print("玩法設定的完整性\n")

    cfg = Config.load()

    # ---- 1. 設定檔一個開關都沒有時，介面仍然要列出全部 ----

    empty = Config.load()
    empty.options = {}
    result = Api._options_json(empty)
    items = result["items"]

    known = set(optionmeta.OPTION_LABELS)
    missing = sorted(known - set(items))
    check(not missing, "設定檔沒有任何開關時仍列出全部",
          f"{len(items)} / {len(known)} 項" + (f"，缺：{missing}" if missing else ""))

    # ---- 2. 沒有鍵掉進「其他」 ----
    other = next((g for g in result["groups"] if g["name"] == "_other"), None)
    check(other is None, "沒有開關掉進「其他」分頁",
          "" if other is None else f"漏登記：{other['keys']}")

    # ---- 3. 每一項都有中文標籤（不是原始鍵名） ----
    raw_names = sorted(k for k, v in items.items() if v["label"] == k)
    check(not raw_names, "每一項都有中文標籤",
          "" if not raw_names else f"顯示原始鍵名：{raw_names}")

    # ---- 4. 範本的預設值 == 腳本裡 ${鍵:預設} 的預設 ----
    tpl = (yaml.safe_load(
        resource_file(".", "config.example.yaml").read_text(encoding="utf-8"))
        or {}).get("options") or {}

    script_defaults: dict[str, set[str]] = {}
    # 走 `resource_files`，打包後腳本在 BUNDLE
    for path in sorted(resource_files("scripts", "*.yaml")):
        for m in re.finditer(r"\$\{([a-z_0-9]+):([^}]*)\}", path.read_text(encoding="utf-8")):
            script_defaults.setdefault(m.group(1), set()).add(m.group(2))

    mismatched = [
        f"{k}：範本 {tpl.get(k)!r} vs 腳本 {sorted(v)}"
        for k, v in sorted(script_defaults.items())
        if k not in tpl or str(tpl[k]) not in {str(x) for x in v}
    ]
    check(not mismatched, "範本的預設值和腳本裡的預設一致",
          f"比對 {len(script_defaults)} 個鍵" + ("；" + "、".join(mismatched) if mismatched else ""))

    # ---- 5. 使用者現在那份設定檔也要列得出全部 ----
    live = Api._options_json(cfg)
    check(set(live["items"]) >= known, "目前的 config.yaml 也列得出全部",
          f"{len(live['items'])} 項")

    print()
    if failures:
        print(f"[失敗] {len(failures)} 項不符預期：" + "、".join(failures))
        return 1
    print("全部通過")
    return 0


if __name__ == "__main__":
    sys.exit(main())
