"""reset() 要把每條規則的 sustain 計時歸零。

排程讓同一個引擎跑下一輪；沒歸零的話，上一輪累積的計時會讓 sustain 規則在新一輪一開始就成立。
"""
import os
import tempfile
import sys, pathlib
from types import SimpleNamespace
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

# ⚠ 測試不寫進真正的 assistant.log，要在 import core 之前設定。
os.environ.setdefault("SSA_LOG_DIR", tempfile.mkdtemp(prefix="ssa-test-log-"))

from core.engine import Engine, Script

ok = True


def check(label, cond):
    global ok
    print(("[通過] " if cond else "[失敗] ") + label)
    ok = ok and bool(cond)


rule = SimpleNamespace(_fires=2, _last_fired=100.0, _since=100.0, _disabled=True, max_fires_daily=0)
e = Engine.__new__(Engine)
e.script = Script.__new__(Script)
e.script.rules = [rule]
e.cfg = SimpleNamespace(options={})
e._measure_logged = {}
e._measure_history = {}
e._apply_options = lambda options: None
Engine.reset(e)

check("reset() 把 sustain 計時歸零", rule._since == 0.0)
check("reset() 把觸發次數歸零", rule._fires == 0)

sys.exit(0 if ok else 1)
