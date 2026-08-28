"""競技場「輸了換對手」的接力：靠 max_fires 前進、靠 reset_fires 歸零。

這條路 selftest 驗不到——它一張畫面一張畫面地判斷，每條規則的計數都從零開始，
而這裡要驗的正是**跨畫面累積下來的計數**。
"""
import os
import tempfile
import sys, pathlib, time
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

# ⚠ **測試不能寫進真正的 assistant.log。** 那是使用者用來監督執行狀況的檔案，
#   混進假的排程與假的下載失敗比沒有紀錄更糟。要在 import core 之前設定。
os.environ.setdefault("SSA_LOG_DIR", tempfile.mkdtemp(prefix="ssa-test-log-"))

from core.config import Config
from core.engine import Engine, Script, apply_options
from core import dailystate, vision

# ⚠ 每日場次上限（arena_max_battles）記在 state.json 裡、**跨執行保留**，所以測試
#   一定要自己隔離——否則機器上今天真的打過的場次會把測試擋掉，看起來像回歸。
_STATE = dailystate.PATH.read_bytes() if dailystate.PATH.exists() else None
dailystate.PATH.unlink(missing_ok=True)

OPTIONS = {"crush_arena": True, "arena_retry_on_loss": True,
           "arena_opponent": 1, "arena_opponent_2": 2, "arena_opponent_3": 3,
           "arena_max_battles": 20}
LIST_PAGE = "samples/arena_opponents.png"
WIN_PAGE = "samples/arena_win.png"
LOSE_PAGE = "samples/arena_lose.png"

cfg = Config.load("dist/config.yaml")


def new_engine():
    script = Script.load("arena", OPTIONS)
    apply_options(script.rules, OPTIONS)
    e = Engine.__new__(Engine)
    e.script, e.cfg, e.device = script, cfg, None
    return e


def step(e, path, sustained=None):
    """餵一張畫面，回傳（規則名稱, 點到的 x）。

    cooldown 一律當成已過；`sustained` 指定的那條規則當作已經連續成立夠久。
    """
    screen = vision.imread_unicode(path)
    for r in e.script.rules:
        r._last_fired = 0.0
        r._since = (time.time() - 9999) if r.name == sustained else 0.0
    hit = e._match_rule(screen)
    if hit is None:
        return "（沒有規則成立）", None
    rule, match = hit
    rule.mark_fired(time.time())
    # 動作只跑 reset_fires——真正的點擊要有裝置，這裡只驗規則怎麼接力。
    for action in rule.actions:
        if "reset_fires" in action:
            e._do("reset_fires", action["reset_fires"], None, None)
    return rule.name, (match.center[0] if match else None)


def check(got, want, what):
    mark = "通過" if got == want else "失敗"
    print(f"  [{mark}] {what}：{got}")
    assert got == want, f"預期 {want}，實際 {got}"


print("=== 1. 連輸三場：第一順位 → 退一格 → 再退一格 → 收工 ===")
e = new_engine()
name, x1 = step(e, LIST_PAGE); check(name, "競技場頁 → 挑對手", "第一場挑第 1 個")
step(e, LOSE_PAGE)
name, x2 = step(e, LIST_PAGE); check(name, "上一場輸了 → 改挑弱一點的對手", "輸了改挑第 2 個")
step(e, LOSE_PAGE)
name, x3 = step(e, LIST_PAGE); check(name, "又輸了 → 挑最後一個對手", "再輸改挑第 3 個")
step(e, LOSE_PAGE)
assert x1 < x2 < x3, f"點擊位置沒有往右移：{x1} {x2} {x3}"
print(f"  [通過] 三次點在不同對手上：x = {x1} → {x2} → {x3}")

# 第四次：三格都用完了，該收工。收工那條有 sustain，把計時往前撥當作已經等夠久
# （selftest 對有 sustain 的規則也是這樣驗的）。
name, _ = step(e, LIST_PAGE, sustained="連續三場都打不贏 → 收工")
check(name, "連續三場都打不贏 → 收工", "三場都輸就收工")

print()
print("=== 2. 贏了要回到第一順位 ===")
e = new_engine()
name, x1 = step(e, LIST_PAGE); check(name, "競技場頁 → 挑對手", "第一場挑第 1 個")
step(e, LOSE_PAGE)
name, x2 = step(e, LIST_PAGE); check(name, "上一場輸了 → 改挑弱一點的對手", "輸了退一格")
name, _ = step(e, WIN_PAGE); check(name, "挑戰勝利 → 點空白處關閉", "贏了")
name, x3 = step(e, LIST_PAGE); check(name, "競技場頁 → 挑對手", "贏了之後回到第一順位")
assert x3 == x1, f"回到第一順位但點的位置不同：{x1} vs {x3}"
print(f"  [通過] 回到同一個位置：x = {x3}")

print()
print("=== 3. 關掉重試就永遠挑同一格 ===")
off = {**OPTIONS, "arena_retry_on_loss": False}
script = Script.load("arena", off)
apply_options(script.rules, off)
e = Engine.__new__(Engine); e.script, e.cfg, e.device = script, cfg, None
name, x1 = step(e, LIST_PAGE); check(name, "競技場頁 → 挑對手", "第一場")
name, _ = step(e, LOSE_PAGE)
check(name, "設定為不換對手 → 關掉結果頁，下一場挑同一格", "輸了，關結果頁並歸零")
name, x2 = step(e, LIST_PAGE); check(name, "競技場頁 → 挑對手", "下一場還是挑同一格")
assert x1 == x2, f"應該挑同一格：{x1} vs {x2}"
print(f"  [通過] 兩場都點在同一個對手上：x = {x1}")

print()
print("=== 4. 打滿設定的場次就收工 ===")
# 上限設 2：第三次開彈窗時應該換成「今天打夠了」那條，而且**還沒按下入場鍵**
two = {**OPTIONS, "arena_max_battles": 2}
script = Script.load("arena", two)
apply_options(script.rules, two)
e = Engine.__new__(Engine); e.script, e.cfg, e.device = script, cfg, None
POPUP = "samples/arena_rank_dialog.png"
for i in (1, 2):
    name, _ = step(e, POPUP)
    check(name, "排位挑戰彈窗 → 按下入場鍵", f"第 {i} 場照常入場")
name, _ = step(e, POPUP)
check(name, "今天打夠了 → 關掉彈窗收工", "第 3 場改成收工")

print()
print("=== 5. reset_fires 指到不存在的規則要在載入時就報錯 ===")
from core.engine import ScriptError
import yaml, tempfile, os
bad = {"name": "壞的", "rules": [
    {"name": "A", "template": "nav_home", "do": [{"reset_fires": "不存在的規則"}]}]}
d = pathlib.Path(tempfile.mkdtemp())
(d / "badscript.yaml").write_text(yaml.safe_dump(bad, allow_unicode=True), encoding="utf-8")
import core.config as _cfgmod
_orig = _cfgmod.resource_file
_cfgmod.resource_file = lambda kind, fn: d / fn if fn.startswith("badscript") else _orig(kind, fn)
import core.engine as _eng
_eng.resource_file = _cfgmod.resource_file
try:
    Script.load("badscript", {})
except ScriptError as ex:
    print(f"  [通過] 載入時就擋下來：{ex}")
else:
    raise AssertionError("打錯規則名稱竟然載入成功")
finally:
    _eng.resource_file = _orig
    _cfgmod.resource_file = _orig

print()
# 還原機器上原本的每日計數，不要因為跑過測試就把今天的場次吃掉。
if _STATE is None:
    dailystate.PATH.unlink(missing_ok=True)
else:
    dailystate.PATH.write_bytes(_STATE)

print("全部通過")
