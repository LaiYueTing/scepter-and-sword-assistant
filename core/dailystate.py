"""跨執行保留的當日計數（`max_fires_daily`、`tally`）。

⚠ 只用在畫面上讀不到次數的情況（例如今天打過幾場競技場），其他判斷一律看畫面。
⚠ 檔案不見、內容損毀或日期不符時，一律當成今天還沒做過。
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from core import logger
from core.config import ROOT

log = logger.get("engine")

# ⚠ 放在 EXE 旁邊（ROOT）：BUNDLE 唯讀，logs/ 會被 `clean` 清掉。
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
    """今天所有項目的計數。"""
    return _load()


def reset(key: str | None = None) -> dict[str, int]:
    """把今天的計數歸零並回傳結果，`key` 留空就是全部。

    ⚠ 引擎在建立時讀入 `_today`，執行中歸零要下一輪才生效。
    """
    remain = {} if key is None else {k: v for k, v in _load().items() if k != key}
    _save(remain)
    return remain
