"""排程的邊界行為。直接 `python tests/test_schedule.py` 跑。

這裡守的是 selftest 涵蓋不到的那一半：selftest 驗的是「這張畫面該觸發哪條
規則」，而排程的錯只在特定的時間點出現，沒有畫面可驗。

主角是 `_passed_during()`——「一個腳本正在跑的時候，別的腳本的時刻經過了」
這件事。實測 2026-08-17 就掉了 21:00 的公會討伐（見那個函式的說明）。
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ⚠ **測試不能寫進真正的 assistant.log。** 那是使用者用來監督執行狀況的檔案，
#   混進假的排程與假的下載失敗比沒有紀錄更糟。要在 import core 之前設定。
os.environ.setdefault("SSA_LOG_DIR", tempfile.mkdtemp(prefix="ssa-test-log-"))

from core.config import Config, TaskConfig          # noqa: E402
from core.runner import Runner                      # noqa: E402

FAILED = 0


def check(what: str, got, want) -> None:
    global FAILED
    ok = got == want
    if not ok:
        FAILED += 1
    print(f"  {'通過' if ok else '失敗'}  {what}")
    if not ok:
        print(f"        得到 {got!r}，預期 {want!r}")


def runner(*tasks: TaskConfig) -> Runner:
    return Runner(Config(path=Path("x")), list(tasks))


def names(tasks: list[TaskConfig]) -> list[str]:
    return [t.name for t in tasks]


def at(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%d %H:%M:%S")


dungeon = TaskConfig(name="dungeon", daily_at="08:00")
daily = TaskConfig(name="daily", daily_at="09:30")
raid = TaskConfig(name="raid", daily_at=["12:30", "21:00"])
arena = TaskConfig(name="arena", weekly_at="週一 08:00")

print("執行期間經過的排定時刻")
r = runner(dungeon, daily, raid, arena)

# 2026-08-17 當天真正發生的事：補跑鏈從 20:59 跑到 21:00:53，21:00 掉了。
check("跑過頭而錯過 21:00 的討伐，要撿回來",
      names(r._passed_during(at("2026-08-17 20:59:21"),
                             at("2026-08-17 21:00:53"))), ["raid"])

# 撿回來之後那一輪自己跑，區間裡就不再有那個時刻——不會沒完沒了。
check("補跑那一輪自己不會再撿到同一格",
      names(r._passed_during(at("2026-08-17 21:01:00"),
                             at("2026-08-17 21:05:00"))), [])

check("執行區間裡沒有任何時刻就回空",
      names(r._passed_during(at("2026-08-17 14:00:00"),
                             at("2026-08-17 14:30:00"))), [])

# 一輪很長時可能同時跨過好幾格，要照時刻先後排，不是照設定檔的次序。
# 同一個時刻（副本與競技場都是 08:00）則保持設定檔的次序——穩定排序。
check("跨過好幾格時照時刻排序",
      names(r._passed_during(at("2026-08-17 07:00:00"),
                             at("2026-08-17 10:00:00"))),
      ["dungeon", "arena", "daily"])

# ⚠ 每週的腳本只在那一天算。拿 times 去比會變成每天都想補跑一次。
check("週一的競技場在週二不算",
      names(r._passed_during(at("2026-08-18 07:00:00"),
                             at("2026-08-18 10:00:00"))), ["dungeon", "daily"])

check("跨午夜時兩天的時刻都看得到",
      names(r._passed_during(at("2026-08-17 20:30:00"),
                             at("2026-08-18 08:30:00"))),
      ["raid", "dungeon"])

# ⚠ 起點退到整分鐘。started 是 datetime.now()，取得的時間點在引擎建好之後
#   （實測 08:00:00.213），而排定時刻是 08:00:00.000——直接比的話，和這一輪排在
#   同一分鐘的腳本永遠差 0.2 秒落在區間外。2026-08-24 就是這樣整格掉了競技場，
#   而那天是週一，「開啟挑戰」與上一期的排名獎勵一起沒了。
start = at("2026-08-17 08:00:00").replace(microsecond=213000)
check("同一分鐘起跑的另一個腳本要撿得到",
      names(r._passed_during(start, at("2026-08-17 09:16:39"), dungeon)),
      ["arena"])

# ⚠ 但剛跑完的那個腳本自己的那一格要排除——它就是被那一格叫起來的，不是錯過。
#   少了這個判斷，清單第一個腳本每天都會多跑一輪。
check("不會把自己剛剛的起跑時刻當成錯過",
      names(r._passed_during(start, at("2026-08-17 09:16:39"), dungeon))
      .count("dungeon"), 0)

# 沒有指名 current 時（舊呼叫方式）行為不變，同一分鐘的兩個都算
check("沒指名 current 就兩個都算",
      names(r._passed_during(start, at("2026-08-17 09:16:39"))),
      ["dungeon", "arena"])

print("\n啟動時的補跑（_missed_today）")

# ⚠ 今天還輪得到的不補跑。討伐 20:32 開機時 12:30 已過，但 21:00 還在，
#   補跑等於把晚上那次次數提前用掉（實測踩過）。
check("今天還有下一格的不補跑",
      names(r._missed_today(at("2026-08-17 20:32:00"))), ["dungeon", "arena", "daily"])

# ⚠ 這個旗標留給「晚一點做就沒意義」的腳本，**討伐已經不用它了**。
#   上一條的「今天還有下一格就不補跑」提供的保護更精確，而關掉補跑會連
#   「21:33 才想起來要開程式」也一起擋掉——那時晚上那格剛過三分鐘，
#   次數不打就是浪費（不會留到隔天）。
check("catch_up: false 的腳本永遠不補跑",
      names(runner(
          TaskConfig(name="dungeon", daily_at=["08:00"]),
          TaskConfig(name="raid", daily_at=["12:30", "21:00"], catch_up=False),
      )._missed_today(at("2026-08-17 23:00:00"))), ["dungeon"])

check("最後一格也過了才補跑",
      names(r._missed_today(at("2026-08-17 21:30:00"))),
      ["dungeon", "arena", "daily", "raid"])

# 使用者的情境：21:00 那格忘了跑，21:33 才想起來。要補。
check("晚上那格遲到三分鐘，討伐仍然補跑",
      "raid" in names(r._missed_today(at("2026-08-17 21:33:00"))), True)

# ⚠ 反過來，中午遲到不補——晚上那格還在，補了等於把它提前用掉。
check("中午那格遲到，討伐不補跑",
      "raid" in names(r._missed_today(at("2026-08-17 12:35:00"))), False)

print()
print("補跑要讓路給快到的排定時刻（_due_soon）")

# ⚠ 這一段守的是使用者實際遇到的情況：20:47 開程式，補跑鏈（副本 → 競技場 →
#   每日活動）會一路輾過 21:00 的討伐。而討伐的價值就在那一刻人最多，事後補
#   等於白補。
def soon(r, when, guard=30):
    r.cfg.runtime.catch_up_guard_minutes = guard
    sched = [t for t in r.tasks if t.times or t.weekly]
    hit = r._due_soon(sched, at(when))
    return hit[1].name if hit else None

r = runner(
    TaskConfig(name="dungeon", daily_at=["08:00"]),
    TaskConfig(name="daily", daily_at=["09:30"]),
    TaskConfig(name="raid", daily_at=["12:30", "21:00"]),
)

check("21:00 的討伐在 20:47 算「快到了」", soon(r, "2026-08-17 20:47:00"), "raid")
check("同一格在 20:29 還不算（差 31 分）", soon(r, "2026-08-17 20:29:00"), None)
check("剛好卡在門檻上算數", soon(r, "2026-08-17 20:30:00"), "raid")
check("差一秒也還算得到", soon(r, "2026-08-17 20:59:59"), "raid")

# ⚠ 時刻**剛好到**的那一秒回 None 是對的，不是漏判：next_scheduled() 只看未來，
#   21:00:00 時它指的已經是下一格了。剛過去的那一格由 _passed_during() 接住並
#   插到佇列最前面——兩個函式的分工就在這條線上。
check("時刻剛好到就換 _passed_during 接手", soon(r, "2026-08-17 21:00:00"), None)
check("guard 設 0 就整個關掉", soon(r, "2026-08-17 20:47:00", guard=0), None)
check("guard 調大就提早讓路", soon(r, "2026-08-17 20:00:00", guard=90), "raid")

# 沒有任何排程時不能誤判成「快到了」，否則 _take_next 會去等一個不存在的時刻
check("完全沒有排程就回 None",
      soon(runner(TaskConfig(name="dungeon", daily_at=[])), "2026-08-17 20:47:00"),
      None)

print()
print("決定這一輪跑誰（_take_next）")

# _due_soon 只回答「近不近」，真正的分岔在 _take_next：近了就讓路（走
# _wait_for_next），不近就先清補跑佇列。時刻用「相對於現在」算，才不必凍結時鐘。
def take(minutes_ahead: int, queue_names: list[str], guard: int = 30,
         once: bool = False):
    """排定時刻在 N 分鐘後，佇列裡有那些人，回傳 (實際跑誰, 有沒有讓路)。"""
    when = datetime.now() + timedelta(minutes=minutes_ahead)
    sched_task = TaskConfig(name="raid", daily_at=[f"{when.hour:02d}:{when.minute:02d}"])
    queue = [TaskConfig(name=n, daily_at=[]) for n in queue_names]
    r = runner(sched_task, *queue)
    r.cfg.runtime.catch_up_guard_minutes = guard
    r.one_shot = once

    yielded = []
    r._wait_for_next = lambda dev, sched: (yielded.append(True), sched_task)[1]
    got = r._take_next(None, queue, [sched_task])
    return (got.name if got else None), bool(yielded)

check("排定時刻 10 分鐘後 → 補跑讓路",
      take(10, ["dungeon", "arena"]), ("raid", True))
check("排定時刻 3 小時後 → 先清補跑佇列",
      take(180, ["dungeon", "arena"]), ("dungeon", False))

# ⚠ 就算「近的那個」和佇列第一個是同一個腳本也要讓路。現在就跑的話，跑完時刻
#   還沒到，等一下會被排程再叫起來跑第二次。
check("同一個腳本也照樣讓路", take(10, ["raid"]), ("raid", True))

check("佇列空了就照常等下一個時刻",
      take(180, []), ("raid", True))

# ⚠ --once 不讓路：人在旁邊手動叫的，要的就是「現在跑」。為了十幾分鐘後的排定
#   時刻先乾等，只會讓人以為程式當住了。
check("--once 不讓路，直接跑", take(10, ["dungeon"], once=True), ("dungeon", False))

print()
if FAILED:
    print(f"有 {FAILED} 項不符預期")
    sys.exit(1)
print("全部符合預期。")
