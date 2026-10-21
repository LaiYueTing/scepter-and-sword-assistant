# -*- coding: utf-8 -*-
"""競技場「週一有券就打完」與引擎 `when_weekday` 的回歸測試：

    python tests/test_monday_use_all.py

⚠ selftest 驗不到——它的引擎沒有旗標，`when_weekday` 一律當成立（否則結果會
跟著跑測試那天是星期幾變），而這裡要驗的正是「週一和其他天走不同條規則」。

把 `core.engine.datetime` 換成固定日期的版本，同一張排位挑戰對話框在週一／週二、
開關開／關、今天已經打滿／還沒打之下，各自該由哪條規則接手。
"""
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ⚠ 測試不能寫進真正的 assistant.log，要在 import core 之前設定。
os.environ.setdefault("SSA_LOG_DIR", tempfile.mkdtemp(prefix="ssa-test-log-"))

from core import engine as engine_mod, vision
from core.config import Config
from core.engine import Engine, Script, ScriptError, _weekdays, apply_options

ok = True


def check(name: str, passed: bool) -> None:
    global ok
    print(f"  [{'通過' if passed else '失敗'}] {name}")
    ok &= passed


MONDAY = datetime(2026, 10, 5, 8, 0)      # 週一
TUESDAY = datetime(2026, 10, 6, 8, 0)


def fixed(day: datetime):
    class _Fixed(datetime):
        @classmethod
        def now(cls, tz=None):
            return day
    return _Fixed


cfg = Config.load(ROOT / "config.example.yaml")
SAMPLE = ROOT / "samples" / "arena_rank_dialog.png"
MON_RULE = "週一開新一期 → 有券就打，不受每日場次上限"
CAP_RULE = "排位挑戰對話框 → 按下入場鍵"
DONE_RULE = "今日場次已達上限 → 關閉對話框並結束本輪"


def winner(day: datetime, battled_today: int, **opts) -> str:
    """在 day 那天、今天已經打了 battled_today 場時，對話框由哪條規則接手。"""
    options = {**cfg.options, "arena_max_battles": 3, **opts}
    sc = Script.load("arena", options)
    for rule in sc.rules:
        rule._today = battled_today if rule.name == CAP_RULE else 0
    apply_options(sc.rules, options)
    e = Engine.__new__(Engine)
    e.script, e.cfg = sc, cfg
    e._flags = set()            # 有旗標的引擎才會看星期幾（selftest 那種不看）
    engine_mod.datetime = fixed(day)
    try:
        hit = e._match_rule(vision.imread_unicode(SAMPLE))
    finally:
        engine_mod.datetime = datetime
    return hit[0].name if hit else ""


if not SAMPLE.is_file():
    print(f"缺少樣本 {SAMPLE.name}，略過（samples/ 不在版控裡）")
    sys.exit(0)

print("=== 1. 週一開著開關：打滿每日上限也照打 ===")
check("週一、已打 3 場 → 週一那條", winner(MONDAY, 3, arena_monday_use_all=True) == MON_RULE)
check("週一、還沒打 → 也是週一那條（不吃每日計數）",
      winner(MONDAY, 0, arena_monday_use_all=True) == MON_RULE)

print("=== 2. 其他天照每日上限 ===")
check("週二、已打 3 場 → 結束本輪", winner(TUESDAY, 3, arena_monday_use_all=True) == DONE_RULE)
check("週二、還沒打 → 一般那條", winner(TUESDAY, 0, arena_monday_use_all=True) == CAP_RULE)

print("=== 3. 開關沒開（或設定檔沒有這個鍵）就和原本一樣 ===")
check("週一、開關 false → 結束本輪", winner(MONDAY, 3, arena_monday_use_all=False) == DONE_RULE)
opts = {k: v for k, v in cfg.options.items() if k != "arena_monday_use_all"}
cfg.options = opts
check("週一、設定檔缺鍵 → 結束本輪", winner(MONDAY, 3) == DONE_RULE)

print("=== 4. 不打排位時，週一的開關不會自己開打 ===")
check("crush_arena 關掉 → 週一那條不啟用",
      winner(MONDAY, 0, arena_monday_use_all=True, crush_arena=False) != MON_RULE)

print("=== 5. when_weekday 的寫法 ===")
check("「週一」→ 0", _weekdays("週一", "x") == [0])
check("清單與英文簡寫", _weekdays(["週六", "sun"], "x") == [5, 6])
try:
    _weekdays("週八", "x")
    check("認不得的要在載入時報錯", False)
except ScriptError:
    check("認不得的要在載入時報錯", True)

print("\n全部通過" if ok else "\n有失敗")
sys.exit(0 if ok else 1)
