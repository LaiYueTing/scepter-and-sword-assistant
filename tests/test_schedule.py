"""排程的邊界行為。直接 `python tests/test_schedule.py` 跑。

涵蓋 `_passed_during()`、`_missed_today()`、`_due_soon()`、`_take_next()`。
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ⚠ 測試不寫進真正的 assistant.log，要在 import core 之前設定。
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

# 補跑從 20:59 跑到 21:00:53，要接住 21:00 那一格。
check("跑過頭而錯過 21:00 的討伐，要接住",
      names(r._passed_during(at("2026-08-17 20:59:21"),
                             at("2026-08-17 21:00:53"))), ["raid"])

# 補跑那一輪的區間不再包含那個時刻，不會一直補跑。
check("補跑那一輪自己不會再接到同一格",
      names(r._passed_during(at("2026-08-17 21:01:00"),
                             at("2026-08-17 21:05:00"))), [])

check("執行區間裡沒有任何時刻就回空",
      names(r._passed_during(at("2026-08-17 14:00:00"),
                             at("2026-08-17 14:30:00"))), [])

# 跨過多格時依時刻排序，同一時刻保持設定檔的次序。
check("跨過好幾格時照時刻排序",
      names(r._passed_during(at("2026-08-17 07:00:00"),
                             at("2026-08-17 10:00:00"))),
      ["dungeon", "arena", "daily"])

# 每週的腳本只在那一天算。
check("週一的競技場在週二不算",
      names(r._passed_during(at("2026-08-18 07:00:00"),
                             at("2026-08-18 10:00:00"))), ["dungeon", "daily"])

check("跨午夜時兩天的時刻都看得到",
      names(r._passed_during(at("2026-08-17 20:30:00"),
                             at("2026-08-18 08:30:00"))),
      ["raid", "dungeon"])

# 起點退到整分鐘：started 比排定時刻晚幾百毫秒。
start = at("2026-08-17 08:00:00").replace(microsecond=213000)
check("同一分鐘起跑的另一個腳本要接得到",
      names(r._passed_during(start, at("2026-08-17 09:16:39"), dungeon)),
      ["arena"])

# 剛跑完的腳本自己的那一格要排除。
check("不會把自己剛剛的起跑時刻當成錯過",
      names(r._passed_during(start, at("2026-08-17 09:16:39"), dungeon))
      .count("dungeon"), 0)

# 沒有指定 current 時，同一分鐘的兩個都算
check("沒指名 current 就兩個都算",
      names(r._passed_during(start, at("2026-08-17 09:16:39"))),
      ["dungeon", "arena"])

print("\n啟動時的補跑（_missed_today）")

# 今天還輪得到的不補跑：20:32 時 12:30 已過，但 21:00 還在。
check("今天還有下一格的不補跑",
      names(r._missed_today(at("2026-08-17 20:32:00"))), ["dungeon", "arena", "daily"])

# catch_up: false 的腳本不補跑（討伐不用這個旗標）。
check("catch_up: false 的腳本永遠不補跑",
      names(runner(
          TaskConfig(name="dungeon", daily_at=["08:00"]),
          TaskConfig(name="raid", daily_at=["12:30", "21:00"], catch_up=False),
      )._missed_today(at("2026-08-17 23:00:00"))), ["dungeon"])

check("最後一格也過了才補跑",
      names(r._missed_today(at("2026-08-17 21:30:00"))),
      ["dungeon", "arena", "daily", "raid"])

# 21:00 那格沒跑到，21:33 才開程式：要補。
check("晚上那格遲到三分鐘，討伐仍然補跑",
      "raid" in names(r._missed_today(at("2026-08-17 21:33:00"))), True)

# 中午遲到不補，晚上那格還在。
check("中午那格遲到，討伐不補跑",
      "raid" in names(r._missed_today(at("2026-08-17 12:35:00"))), False)

print()
print("補跑要讓路給快到的排定時刻（_due_soon）")

# 下一個排定時刻在 catch_up_guard_minutes 之內時，補跑要讓路。
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

# 時刻剛好到的那一秒回傳 None：next_scheduled() 只看未來，剛過去的由 _passed_during() 接住。
check("時刻剛好到就換 _passed_during 接手", soon(r, "2026-08-17 21:00:00"), None)
check("guard 設 0 就整個關掉", soon(r, "2026-08-17 20:47:00", guard=0), None)
check("guard 調大就提早讓路", soon(r, "2026-08-17 20:00:00", guard=90), "raid")

# 沒有任何排程時回傳 None
check("完全沒有排程就回 None",
      soon(runner(TaskConfig(name="dungeon", daily_at=[])), "2026-08-17 20:47:00"),
      None)

print()
print("決定這一輪跑誰（_take_next）")

# _take_next 的分岔：近了就讓路，不近就先清補跑佇列。時刻相對於現在計算。
def take(minutes_ahead: int, queue_names: list[str], guard: int = 30,
         once: bool = False):
    """排定時刻在 N 分鐘後，給定佇列，回傳 (實際跑誰, 是否讓路)。"""
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

# 近的那個和佇列第一個是同一個腳本時也要讓路。
check("同一個腳本也照樣讓路", take(10, ["raid"]), ("raid", True))

check("佇列空了就照常等下一個時刻",
      take(180, []), ("raid", True))

# --once 不讓路。
check("--once 不讓路，直接跑", take(10, ["dungeon"], once=True), ("dungeon", False))

print()
if FAILED:
    print(f"有 {FAILED} 項不符預期")
    sys.exit(1)
print("全部符合預期。")
