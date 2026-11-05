"""副本領獎的天花板閘門：詳情頁看到的事實，靠旗標帶到結算頁去用。

驗上一個畫面設定的旗標（selftest 沒有跨畫面的旗標）。
"""
import os
import tempfile
import sys, pathlib, time
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

# ⚠ 測試不寫進真正的 assistant.log，要在 import core 之前設定。
os.environ.setdefault("SSA_LOG_DIR", tempfile.mkdtemp(prefix="ssa-test-log-"))

from core.config import Config
from core.engine import Engine, Script, ScriptError, apply_options
from core import dailystate, vision

# ⚠ 「先把領獎次數買滿」的計數記在 state.json，測試要自己隔離。
_STATE = dailystate.PATH.read_bytes() if dailystate.PATH.exists() else None
dailystate.PATH.unlink(missing_ok=True)

# ⚠ like_teammates 關閉：「幫隊友按讚」排在領獎前面而且沒有 cooldown。
OPTIONS = {"claim_reward": True, "stop_when_no_count": True,
           "auto_battle_mode": True, "accept_with_partners": True,
           "like_teammates": False,
           "stock_up_before_new_dungeon": True}
DETAIL_S = "samples/detail_ready.png"        # 赤炎之楔・惡夢：已經是 S，沒有頁籤掛 🔒
DETAIL_A = "samples/detail_nightmare.png"    # 月之宮殿・惡夢：最高只到 A
RESULT_S = "samples/result_s.png"
UNLOCK = "samples/dungeon_unlock_ready.png"  # 條件達成，亮綠「解鎖」

cfg = Config.load("dist/config.yaml")


def new_engine():
    script = Script.load("dungeon", OPTIONS)
    apply_options(script.rules, OPTIONS)
    e = Engine.__new__(Engine)
    e.script, e.cfg, e.device = script, cfg, None
    e._flags = set()          # ⚠ 沒有這一行，_condition 會整個跳過旗標判斷
    return e


def step(e, path, busy=()):
    """餵一張畫面並執行旗標動作。`busy` 裡的規則當成剛觸發過（還在 cooldown）。"""
    screen = vision.imread_unicode(path)
    now = time.time()
    for r in e.script.rules:
        r._last_fired = now if r.name in busy else 0.0
        r._since = 0.0
    hit = e._match_rule(screen)
    if hit is None:
        return "（沒有規則成立）"
    rule, _ = hit
    rule.mark_fired(now)
    for action in rule.actions:
        for verb in ("set_flag", "clear_flag"):
            if verb in action:
                e._do(verb, action[verb], None, None)
    return rule.name


def check(got, want, what):
    mark = "通過" if got == want else "失敗"
    print(f"  [{mark}] {what}：{got}")
    assert got == want, f"預期 {want}，實際 {got}"


# 配對那條排在最高難度判斷前面，當成剛觸發過才輪得到底下那幾條。
MATCHING = "副本詳情頁 → 確認副本後配對"

print("=== 1. 還沒確認天花板時，拿到 S 也不領獎 ===")
e = new_engine()
check(step(e, RESULT_S), "尚可解鎖更高難度 → 取得 S 級仍不領獎", "旗標沒設就不領")

print()
print("=== 2. 詳情頁確認過天花板之後才領 ===")
check(step(e, DETAIL_S, busy=[MATCHING]),
      "這一級已是 S 而沒有難度等著解鎖 → 已在最高難度", "詳情頁設下旗標")
assert "已在最高難度" in e._flags, e._flags
check(step(e, RESULT_S), "結算 S 級 → 領取獎勵", "設了旗標就領獎")

print()
print("=== 3. 這一級還沒拿到 S 就不算天花板 ===")
e = new_engine()
# 配對那條當成剛觸發過，結果是純攔截，代表三條最高難度規則都不成立。
check(step(e, DETAIL_A, busy=[MATCHING]), "配對中 → 留在原地等待",
      "只有 A 級：天花板規則全部不成立")
assert not e._flags, e._flags

print()
print("=== 4. 解鎖上一級之後旗標要歸零 ===")
e = new_engine()
step(e, DETAIL_S, busy=[MATCHING])
assert "已在最高難度" in e._flags
check(step(e, UNLOCK), "下一難度可以解鎖 → 按下解鎖", "解鎖")
assert not e._flags, f"解鎖後旗標沒清乾淨：{e._flags}"
print("  [通過] 解鎖後旗標歸零")

print()
print("=== 5. 新副本明天開放：不領獎、先買次數、一場結束就結束本輪 ===")
e = new_engine()
e._flags.add("明天開新副本")
check(step(e, DETAIL_S, busy=[MATCHING]), "明天開新副本 → 先把領獎次數買滿",
      "詳情頁先去買次數")
check(step(e, RESULT_S), "明天開放新副本 → 本日不領獎，本場結束後結束本輪",
      "結算頁不領獎")

print()
print("=== 6. 沒有這個旗標時行為完全不變 ===")
e = new_engine()
check(step(e, DETAIL_S, busy=[MATCHING]),
      "這一級已是 S 而沒有難度等著解鎖 → 已在最高難度", "詳情頁照常")
check(step(e, RESULT_S), "結算 S 級 → 領取獎勵", "結算頁照常領獎")

if _STATE is not None:
    dailystate.PATH.write_bytes(_STATE)
else:
    dailystate.PATH.unlink(missing_ok=True)

print()
print("全部通過。")
