# -*- coding: utf-8 -*-
"""`claim_rank_a_after`：連續幾場拿不到 S 之後，A 也領獎。

    python tests/test_claim_rank_a.py

計數靠「結算未達 S → 退出重打」的 max_fires，用完才輪得到「A 也領獎」那條。
selftest 驗不到：它每一張畫面的計數都從零開始，而這裡要驗的正是**跨畫面累積的
次數**。畫面用假的比對結果餵（`_find` 換成查表），不碰模擬器。
"""
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("SSA_LOG_DIR", tempfile.mkdtemp(prefix="ssa-test-log-"))

import numpy as np

from core.config import Config
from core.engine import Engine, Script, apply_options
from core.vision import Match

ok = True


def check(name, got, want):
    global ok
    passed = got == want
    ok &= passed
    print(f"  [{'通過' if passed else '失敗'}] {name}：{got}" + ("" if passed else f"（預期 {want}）"))


BASE = {"claim_reward": True, "stop_when_no_count": True, "auto_battle_mode": True,
        "accept_with_partners": True, "like_teammates": False}
cfg = Config.load(ROOT / "config.example.yaml")
SCREEN = np.zeros((1280, 720, 3), dtype=np.uint8)


def new_engine(after, flags=("已在最高難度",)):
    options = {**BASE, "claim_rank_a_after": after}
    script = Script.load("dungeon", options)
    apply_options(script.rules, options)
    e = Engine.__new__(Engine)
    e.script, e.cfg, e.device = script, cfg, None
    e._flags = set(flags)
    e._measure_cache = {}
    return e


def settle(e, present):
    """餵一張「畫面上有這些模板」的結算頁，回傳觸發的規則名稱。"""
    e._find = lambda screen, name, th, region=None: (
        Match(name, 1.0, 300, 200, 40, 40) if name in present else None)
    e._find_all = lambda *a, **k: []
    e._find_cache = {}
    for r in e.script.rules:
        r._since = 0.0
    hit = e._match_rule(SCREEN)
    if hit is None:
        return "（沒有規則成立）"
    hit[0].mark_fired(time.time())
    return hit[0].name


A = {"btn_claim_reward", "rank_a"}
B = {"btn_claim_reward", "rank_b"}
RETRY = "結算未達 S → 放棄領取，退出重打"
CLAIM_A = "打了幾場都拿不到 S → A 也領獎"
RETRY_B = "打了幾場都拿不到 S 但這場連 A 都不到 → 退出重打"

print("=== 預設 0：一直打到 S 為止 ===")
e = new_engine(0)
for i in range(5):
    check(f"第 {i + 1} 場 A", settle(e, A), RETRY)

print("=== 設 2：兩場沒 S 之後，A 也領 ===")
e = new_engine(2)
check("第 1 場 A", settle(e, A), RETRY)
check("第 2 場 B", settle(e, B), RETRY)
check("第 3 場 A", settle(e, A), CLAIM_A)
check("第 4 場 B 仍然退出重打", settle(e, B), RETRY_B)

print("=== 設 2 但還沒到最高難度：A 不領 ===")
e = new_engine(2, flags=())
settle(e, A); settle(e, A)
check("第 3 場 A", settle(e, A), RETRY_B)

print("=== 認不出「領取獎勵」按鈕時不能越過計數 ===")
e = new_engine(2)
check("只認得 rank_a", settle(e, {"rank_a"}), "（沒有規則成立）")

print()
print("全部通過" if ok else "有項目失敗")
sys.exit(0 if ok else 1)
