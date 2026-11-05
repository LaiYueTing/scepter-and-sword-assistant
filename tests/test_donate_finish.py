# -*- coding: utf-8 -*-
"""公會捐獻要捐到設定的次數才結束本輪，以及引擎的 `when_spent`。

    python tests/test_donate_finish.py

用同一張捐獻面板逐秒模擬，數「花晨星捐贈」在結束本輪之前觸發幾次。

不碰模擬器也不寫 state.json：觸發只改規則自己的計數。
"""
import os
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("SSA_LOG_DIR", tempfile.mkdtemp(prefix="ssa-test-log-"))

import core.engine as engine_mod
from core import vision
from core.config import Config
from core.engine import Engine, Script, ScriptError, apply_options

ok = True
STAR = "捐獻面板 → 花晨星捐贈"
DONE = "今日捐獻已達設定次數 → 關閉面板並結束本輪"


def check(name, passed, detail=""):
    global ok
    ok &= bool(passed)
    print(f"  [{'通過' if passed else '失敗'}] {name}" + (f"　{detail}" if detail else ""))


cfg = Config.load(ROOT / "config.example.yaml")
screen = vision.imread_unicode(str(ROOT / "samples" / "chores_donate_star.png"))


def simulate(options, drop_when_spent=False, seconds=60):
    """回傳（結束本輪之前花晨星捐贈觸發了幾次, 有沒有結束本輪）。"""
    script = Script.load("chores", options)
    apply_options(script.rules, options)
    eng = Engine.__new__(Engine)
    eng.script, eng.cfg, eng._flags = script, cfg, set()
    eng._match_frame, eng._measure_frame = {}, {}
    rules = {r.name: r for r in script.rules}
    for r in script.rules:
        r._today = r._fires = 0
        r._last_fired = r._since = 0.0
    if drop_when_spent:
        rules[DONE].when_spent = []

    clock = [1000.0]
    real_time = engine_mod.time
    engine_mod.time = types.SimpleNamespace(time=lambda: clock[0])
    try:
        stars = 0
        for _ in range(seconds):
            hit = eng._match_rule(screen)
            if hit:
                rule = hit[0]
                if rule.name == DONE:
                    return stars, True
                rule._last_fired = clock[0]
                rule._fires += 1
                if rule.max_fires_daily:
                    rule._today += 1
                if rule.name == STAR:
                    stars += 1
            clock[0] += 1.0
    finally:
        engine_mod.time = real_time
    return stars, False


options = dict(cfg.options)
options.update(chores_donate=True, guild_donate_stars=True, guild_donate_star_times=4)

stars, done = simulate(options, drop_when_spent=True)
check("對照組：沒有 when_spent 時會提早結束（重現問題）", done and stars < 4, f"捐了 {stars} 次")

stars, done = simulate(options)
check("捐滿 4 次才結束本輪", done and stars == 4, f"捐了 {stars} 次")

options["guild_donate_star_times"] = 2
stars, done = simulate(options)
check("設定 2 次就捐 2 次", done and stars == 2, f"捐了 {stars} 次")

options["guild_donate_stars"] = False
stars, done = simulate(options)
check("關閉晨星捐獻時直接結束本輪", done and stars == 0, f"捐了 {stars} 次")

import yaml

raw = yaml.safe_load((ROOT / "scripts" / "chores.yaml").read_text(encoding="utf-8"))
raw["rules"][0]["when_spent"] = "不存在的規則"
tmp = Path(tempfile.mkdtemp()) / "chores_bad.yaml"
tmp.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
real = engine_mod.resource_file
engine_mod.resource_file = lambda kind, name: tmp
try:
    Script.load("chores_bad", {})
    check("when_spent 指到不存在的規則要在載入時報錯", False)
except ScriptError as e:
    check("when_spent 指到不存在的規則要在載入時報錯", "when_spent" in str(e))
finally:
    engine_mod.resource_file = real

print()
print("全部通過" if ok else "有項目失敗")
sys.exit(0 if ok else 1)
