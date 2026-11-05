"""`finish: skip_cleanup` 要真的跳過 on_finish，而且只跳這一輪。

用於伺服器維護中：結束程序的每一步都會等 25 秒。
"""
import os
import tempfile
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

# ⚠ 測試不寫進真正的 assistant.log，要在 import core 之前設定。
os.environ.setdefault("SSA_LOG_DIR", tempfile.mkdtemp(prefix="ssa-test-log-"))

from core.engine import Engine, Script, ScriptError

ok = True


def check(label, cond):
    global ok
    print(("[通過] " if cond else "[失敗] ") + label)
    ok = ok and bool(cond)


class FakeDevice:
    """回傳固定畫面，只驗結束程序有沒有執行。"""

    def __init__(self):
        self.calls = 0

    def screencap(self):
        self.calls += 1
        return None


def new_engine(steps):
    e = Engine.__new__(Engine)
    e.script = Script.__new__(Script)
    e.script.on_finish = steps
    e.dry_run = False
    e._skip_cleanup = False
    e._finishing = False
    e._stop = False
    e.device = FakeDevice()
    e._status_hook = None
    return e


# ---------- 一般的 finish：結束程序照跑 ----------
e = new_engine([{"log": "本輪結束"}])
e._do("finish", None, None, None)
check("一般的 finish 不會設 skip_cleanup", e._skip_cleanup is False)
check("一般的 finish 會停下這一輪", e._stop is True)
e._run_on_finish()
check("一般的 finish 仍然跑結束程序", e.device.calls == 1)

# ---------- finish: skip_cleanup：結束程序整段跳過 ----------
e = new_engine([{"log": "本輪結束"}])
e._do("finish", "skip_cleanup", None, None)
check("skip_cleanup 會設旗標", e._skip_cleanup is True)
check("skip_cleanup 一樣會停下這一輪", e._stop is True)
e._run_on_finish()
check("skip_cleanup 不會去抓畫面，也就不會跑結束程序", e.device.calls == 0)

# ---------- 只跳這一輪 ----------
# 排程用同一個引擎跑下一輪，reset() 要把旗標歸零。
e.completed = 1
e.yielded = False
e._last_change = 0.0
e._prev_frame = None
e._waiting_name = None
e._waiting_block_start = 0.0
e._measure_logged = {}
e._measure_history = {}
e._last_log_text = ""
e.script.rules = []
e.cfg = type("C", (), {"options": {}})()
e._options_logged = True
Engine.reset(e)
check("reset() 會把旗標清掉", e._skip_cleanup is False)

# ---------- 參數錯誤在載入時報錯 ----------
try:
    Script.load("dungeon")
    loaded = True
except ScriptError as err:
    loaded, msg = False, str(err)
check("五份腳本裡的 finish 參數都合法", loaded)

import core.engine as engine_mod
import yaml as _yaml

bad = {
    "name": "測試",
    "rules": [{"name": "打錯字 → 結束本輪", "template": "nav_home",
               "do": [{"finish": "skip-cleanup"}]}],
}
orig = engine_mod.resource_file
tmp = pathlib.Path(tempfile.mkdtemp(prefix="ssa-test-script-")) / "bad.yaml"
tmp.write_text(_yaml.safe_dump(bad, allow_unicode=True), encoding="utf-8")
engine_mod.resource_file = lambda kind, fn: tmp
try:
    Script.load("bad")
    check("finish 的參數打錯字會在載入時報錯", False)
except ScriptError as err:
    check("finish 的參數打錯字會在載入時報錯", "skip_cleanup" in str(err))
finally:
    engine_mod.resource_file = orig

print()
print("全部通過" if ok else "有項目失敗")
sys.exit(0 if ok else 1)
