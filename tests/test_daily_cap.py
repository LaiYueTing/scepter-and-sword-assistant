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

    print("=== 6. 介面看得到、也重設得掉 ===")
    OTHER = "chores/捐獻面板 → 花晨星捐贈"
    def seed(counts):
        dailystate.PATH.write_text(
            json.dumps({"date": date.today().isoformat(), "counts": counts},
                       ensure_ascii=False), encoding="utf-8")
    seed({KEY: 3, OTHER: 2})
    check("counts() 讀得到全部", dailystate.counts() == {KEY: 3, OTHER: 2})
    dailystate.reset(KEY)
    check("只清掉指定的那一項", dailystate.counts() == {OTHER: 2})
    dailystate.reset()
    check("留空就是全部清掉", dailystate.counts() == {})

    print("=== 7. tally：只數不擋 ===")
    from core.engine import Script, ScriptError
    sc = Script.load("raid", cfg.options)
    joins = [r for r in sc.rules
             if any(a.get("tally") == "參戰" for a in r.actions)]
    # 討伐有四種入場方式，全部數進同一格——「今天參戰幾次」是一件事。
    check("四條入場規則共用同一格", len(joins) == 4)
    check("腳本知道自己的鍵前綴", sc.stem == "raid")

    seed({})
    e = Engine.__new__(Engine)
    e.script, e.dry_run, e.device = sc, False, None
    e._flags = set()
    for _ in range(9):
        e._do("tally", "參戰", None, None)
    check("數到 9 也不會停", dailystate.counts().get("raid/參戰") == 9)
    # ⚠ 這是 tally 和 max_fires_daily 的唯一差別，也是它存在的理由：規則的
    #   ready() 完全不看它。
    check("規則仍然可以觸發", joins[0].ready(time.time()))

    print("=== 8. 打錯的 tally 要在載入時就擋下來 ===")
    # ⚠ tally 只數不擋，所以打錯了**沒有任何症狀**——面板上少一列而已，
    #   而那正是沒有人會發現的那種錯。所以形狀要在載入時就驗。
    import tempfile as _tf

    import yaml as _yaml

    import core.engine as _eng

    def load_inline(rules):
        tmp = Path(_tf.mkdtemp()) / "inline.yaml"
        tmp.write_text(_yaml.safe_dump({"name": "測試", "rules": rules},
                                       allow_unicode=True), encoding="utf-8")
        real = _eng.resource_file
        _eng.resource_file = lambda kind, fn: tmp
        try:
            return Script.load("inline"), ""
        except ScriptError as err:
            return None, str(err)
        finally:
            _eng.resource_file = real

    _, err = load_inline([{"name": "X → Y", "template": "nav_home",
                           "max_fires_daily": 2, "do": [{"tally": "Z"}]}])
    check("同時有 tally 與 max_fires_daily 會被擋下", "數兩次" in err)
    _, err = load_inline([{"name": "X → Y", "template": "nav_home",
                           "do": [{"tally": ""}]}])
    check("tally 沒給名稱也會被擋下", "要給一個名稱" in err)

    print("=== 7. 方法表：列得出上限，執行中不給重設 ===")
    from gui.api import Api

    class _Channel:
        def send(self, *a, **k):
            pass

    api = Api(_Channel())
    api._cfg = cfg
    seed({KEY: 3, "arena/這條規則已經改名了 → 動作": 1})
    rows = {r["key"]: r for r in api.daily_state({})["rows"]}
    check("帶得出今天的次數與上限",
          rows[KEY]["done"] == 3 and rows[KEY]["limit"] == 3)
    # ⚠ 被計數的是**動作**（打一場、捐一次），所以標籤取「→」後面那半。
    check("標籤取「→」後面那半", rows[KEY]["label"] == "按下入場鍵")
    # ⚠ 狀態檔裡有、現在的腳本裡沒有的鍵也要列出來——它仍然佔著位子，而使用者
    #   正是來這裡找「為什麼今天不打了」的。
    check("腳本裡已經沒有的鍵仍然列得出來",
          "arena/這條規則已經改名了 → 動作" in rows)

    api._runner = type("_R", (), {"is_alive": staticmethod(lambda: True)})()
    try:
        api.daily_reset({})
        guarded = False
    except RuntimeError:
        guarded = True
    # ⚠ 引擎是在**建立時**把計數讀進規則裡的，執行中歸零要下一輪才生效——
    #   「按了看起來沒作用」是最難查的那種形狀，所以後端直接擋下來。
    check("執行中不給重設", guarded)
    check("而且真的一個都沒被清掉", dailystate.counts().get(KEY) == 3)
    api._runner = None
    api.daily_reset({"key": KEY})
    check("停下來之後重設得掉", dailystate.counts().get(KEY) is None)
finally:
    if BACKUP is None:
        dailystate.PATH.unlink(missing_ok=True)
    else:
        dailystate.PATH.write_bytes(BACKUP)

print("\n" + ("全部通過" if ok else "有失敗項目"))
sys.exit(0 if ok else 1)
