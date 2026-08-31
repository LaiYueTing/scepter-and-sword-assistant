"""跨執行保留的「今天做了幾次」。

引擎的 `max_fires` 是**每輪**重置的（`Engine.reset()` 會把計數清掉），所以拿它當
「每天最多幾次」會在補跑或手動重跑時重新計數——設 3 場，跑兩輪就變成 6 場。
這支模組讓那種上限跨執行保留。

⚠ **這是刻意的例外，不是通則。** 專案的原則是「不記錄今天跑過沒，因為腳本會進
  遊戲自己確認」——而那條的前提是**答案寫在畫面上**。「今天打過幾場競技場」遊戲
  沒有顯示（只顯示剩幾張券），所以那個前提不成立，才需要自己記。判斷要不要用
  這支模組時就問這一句：**那個數字，畫面上看得到嗎？**

⚠ **壞掉要能安全退化。** 檔案不見、內容壞掉、日期對不上，一律當成「今天還沒做過」
  ——也就是退回沒有這支模組時的行為。少算一次的代價遠小於「因為狀態檔壞掉而整個
  不執行」。
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from core import logger
from core.config import ROOT

log = logger.get("engine")

# ⚠ 要放在 EXE 旁邊（ROOT），不能放 BUNDLE——那是唯讀的暫存目錄，而且每次執行
#   路徑都不同。放 logs/ 底下則會被 `clean` 一起掃掉。
PATH = ROOT / "state.json"


def _load() -> dict[str, Any]:
    """讀出今天的計數。不是今天的、或讀不出來，都當成空的。"""
    try:
        raw = json.loads(PATH.read_text(encoding="utf-8"))
        if raw.get("date") == date.today().isoformat():
            counts = raw.get("counts")
            if isinstance(counts, dict):
                return {k: int(v) for k, v in counts.items()
                        if isinstance(v, (int, float))}
    except (OSError, ValueError, TypeError):
        pass
    return {}


def get(key: str) -> int:
    """今天這個項目已經做了幾次。"""
    return _load().get(key, 0)


def _save(counts: dict[str, int]) -> None:
    """寫回今天的計數。寫不進去只記一行 debug，不中斷流程。"""
    try:
        PATH.write_text(
            json.dumps({"date": date.today().isoformat(), "counts": counts},
                       ensure_ascii=False, indent=2),
            encoding="utf-8", newline="")
    except OSError as e:
        log.debug("每日計數寫不進 %s：%s", PATH, e)


def add(key: str, amount: int = 1) -> int:
    """記一次，回傳累計值。"""
    counts = _load()
    counts[key] = counts.get(key, 0) + amount
    _save(counts)
    return counts[key]


def counts() -> dict[str, int]:
    """今天所有項目的計數。介面要把它畫出來，所以要有一個公開的入口。"""
    return _load()


def reset(key: str | None = None) -> dict[str, int]:
    """把今天的計數歸零並回傳歸零後的結果。`key` 留空就是全部。

    ⚠ 執行中不要動它。引擎是在建立時把 `_today` 讀進規則裡的，改了要下一輪才
      生效——而在那之前使用者看到的數字和引擎手上的那份是兩回事。
    """
    remain = {} if key is None else {k: v for k, v in _load().items() if k != key}
    _save(remain)
    return remain
