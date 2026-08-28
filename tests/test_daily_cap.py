# -*- coding: utf-8 -*-
"""每日上限 `max_fires_daily` 的回歸測試：

    python tests/test_daily_cap.py

⚠ selftest 驗不到——那支一張畫面判一次規則，每條規則的計數都從零開始，而這裡
要驗的正是**跨執行保留下來的計數**。

要守住四件事：**同一輪內會擋**、**重新執行仍然記得**（`max_fires` 就是敗在這裡）、
**換一天自動歸零**、**狀態檔壞掉要安全退化**。
"""
import json
import os
import sys
import tempfile
import time
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ⚠ **測試不能寫進真正的 assistant.log。** 那是使用者用來監督執行狀況的檔案，
#   混進假的排程與假的下載失敗比沒有紀錄更糟。要在 import core 之前設定。
os.environ.setdefault("SSA_LOG_DIR", tempfile.mkdtemp(prefix="ssa-test-log-"))

from core import dailystate
from core.config import Config
from core.engine import Engine, Script

ok = True


def check(name: str, passed: bool) -> None:
    global ok
    print(f"  [{'通過' if passed else '失敗'}] {name}")
    ok &= passed


cfg = Config.load(ROOT / "dist" / "config.yaml")
KEY = "arena/排位挑戰彈窗 → 按下入場鍵"
BACKUP = dailystate.PATH.read_bytes() if dailystate.PATH.exists() else None


def fresh(cap: int = 3):
    """載入一份新的 arena 腳本（模擬「重新執行程式」）。"""
    sc = Script.load("arena", {**cfg.options, "arena_max_battles": cap})
    return [r for r in sc.rules if r.name.startswith("排位挑戰彈窗")][0]


def fire(rule, n: int) -> int:
    """試著觸發 n 次，回傳實際成功幾次。"""
    got = 0
    for i in range(n):
        t = time.time() + i * 10
        if rule.ready(t):
            rule.mark_fired(t)
            got += 1
    return got


try:
    dailystate.PATH.unlink(missing_ok=True)

    print("=== 1. 同一輪內打滿就擋下來 ===")
    r = fresh(3)
    check("上限 3，試 5 次只成功 3 次", fire(r, 5) == 3)

    print("=== 2. 重新執行仍然記得（max_fires 就是敗在這裡）===")
    r2 = fresh(3)
    check("新載入的規則知道今天已經打了 3 場", r2._today == 3)
    check("再試也不會觸發", fire(r2, 3) == 0)

    print("=== 3. reset()（排程的下一輪）不會把它歸零 ===")
    sc = Script.load("arena", {**cfg.options, "arena_max_battles": 3})
    e = Engine.__new__(Engine)
    e.script, e.cfg, e.device = sc, cfg, None
    e._stop_event = __import__("threading").Event()
    e.completed = 0
    e._measure_logged, e._measure_history = {}, {}
    e._options_logged = True
    e._last_change, e._prev_frame = time.time(), None
    e._waiting_name, e._waiting_block_start = None, 0.0
    e._stop, e._finishing, e._last_log_text = False, False, ""
    e.reset()
    r3 = [x for x in sc.rules if x.name.startswith("排位挑戰彈窗")][0]
    check("reset 之後仍然是 3", r3._today == 3)
    check("其他規則的 max_fires 有被歸零",
          all(x._fires == 0 for x in sc.rules))

    print("=== 4. 換一天自動歸零 ===")
    stale = {"date": (date.today() - timedelta(days=1)).isoformat(),
             "counts": {KEY: 9}}
    dailystate.PATH.write_text(json.dumps(stale), encoding="utf-8")
    check("昨天的計數不算數", fresh(3)._today == 0)

    print("=== 5. 狀態檔壞掉要安全退化（當成今天還沒做過）===")
    dailystate.PATH.write_text("{ 這不是 JSON", encoding="utf-8")
    check("壞檔不會拋錯，計數當 0", fresh(3)._today == 0)
    dailystate.PATH.unlink(missing_ok=True)
    check("檔案不存在也當 0", fresh(3)._today == 0)
finally:
    if BACKUP is None:
        dailystate.PATH.unlink(missing_ok=True)
    else:
        dailystate.PATH.write_bytes(BACKUP)

print("\n" + ("全部通過" if ok else "有失敗項目"))
sys.exit(0 if ok else 1)
