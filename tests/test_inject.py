# -*- coding: utf-8 -*-
"""排程等待中塞一個腳本進去跑（介面上的「虛空裂縫」按鈕）：

    python tests/test_inject.py

虛空裂縫每兩週開一次、要人先組好隊伍，排不了程；使用者要的是「就算排程正在
背景等，按下去也要能打」。`Runner.inject()` 守三件事：

  1. 等待中被塞進來 → 立刻醒來跑它，跑完回去等原本的下一個時刻（不是結束）
  2. 正在跑別的腳本時塞進來 → 接在那一輪後面，不打斷正在打的那一場
  3. 塞進來的那一輪**不讓位**（`until=None`）：那是使用者明確要求的，排定時刻在
     中途到了也讓它打完

⚠ selftest 涵蓋不到（那支驗的是規則），這裡把 Engine 與 Device 換成假的。
"""
import os
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("SSA_LOG_DIR", tempfile.mkdtemp(prefix="ssa-test-log-"))

import core.runner as runner_mod
from core.config import Config, TaskConfig

ok = True


def check(name: str, passed: bool, detail: str = "") -> None:
    global ok
    ok &= bool(passed)
    print(f"  [{'通過' if passed else '失敗'}] {name}" + (f"　{detail}" if detail else ""))


class FakeEngine:
    """記下每一輪的（腳本名, until），並讓每一輪跑一小段時間。"""

    runs: list[tuple[str, object]] = []
    hold = 0.0              # 每一輪要耗多久（模擬「正在打」）

    def __init__(self, device, script, repeat=0, dry_run=False,
                 stop_event=None, status_hook=None):
        self.script = script
        self.completed = 0
        self.yielded = False

    def reset(self) -> None:
        self.completed = 0
        self.yielded = False

    def run(self, until=None) -> None:
        FakeEngine.runs.append((self.script.name, until))
        time.sleep(FakeEngine.hold)
        self.completed = 1


class FakeDevice:
    def __init__(self, cfg):
        pass

    def connect(self):
        return None


def build_runner() -> runner_mod.Runner:
    """一個排程腳本：雜務，排在兩分鐘後（跑完啟動那一輪就會進入等待）。"""
    now = datetime.now()
    later = (now + timedelta(minutes=2)).strftime("%H:%M")
    cfg = Config(path=Path("x"))
    cfg.device.serial = "auto"
    cfg.runtime.catch_up = True
    cfg.runtime.catch_up_guard_minutes = 0
    cfg.tasks = [TaskConfig(name="chores", enabled=True, daily_at=[later], repeat=1)]
    return runner_mod.Runner(cfg, cfg.tasks)


def drive(hold: float, inject_after: float) -> tuple[list, bool, bool]:
    """跑一個 Runner，在 inject_after 秒後塞入虛空裂縫，回傳（各輪, 塞入時 waiting, 之後有沒有回到等待）。"""
    FakeEngine.runs = []
    FakeEngine.hold = hold
    real_engine, real_device = runner_mod.Engine, runner_mod.Device
    runner_mod.Engine, runner_mod.Device = FakeEngine, FakeDevice
    try:
        r = build_runner()
        t = threading.Thread(target=r.run, daemon=True)
        t.start()
        time.sleep(inject_after)
        was_waiting = r.inject(TaskConfig(name="rift"))
        # 等它跑完塞進去的那一輪
        deadline = time.time() + 10
        while time.time() < deadline and not any(n == "虛空裂縫" for n, _ in FakeEngine.runs):
            time.sleep(0.1)
        time.sleep(hold + 1.5)      # 讓那一輪跑完、回到等待
        back_waiting = r.waiting and t.is_alive()
        r.stop()
        t.join(timeout=5)
    finally:
        runner_mod.Engine, runner_mod.Device = real_engine, real_device
    return FakeEngine.runs, was_waiting, back_waiting


def main() -> int:
    print("等待中塞進來 → 立刻跑，跑完回去等")
    runs, was_waiting, back_waiting = drive(hold=0.0, inject_after=2.0)
    names = [n for n, _ in runs]
    print(f"    實際跑的順序：{names}")
    check("inject() 回報「馬上開始」", was_waiting is True)
    check("虛空裂縫真的跑了", "虛空裂縫" in names)
    check("跑完之後回到等待，排程沒有結束", back_waiting)
    until = dict(runs).get("虛空裂縫", "沒跑")
    check("塞進來的那一輪不讓位（until=None）", until is None, f"until={until}")

    print("正在跑別的腳本時塞進來 → 接在那一輪後面")
    runs, was_waiting, _ = drive(hold=3.0, inject_after=0.8)
    names = [n for n, _ in runs]
    print(f"    實際跑的順序：{names}")
    check("inject() 回報「排在後面」", was_waiting is False)
    check("雜務那一輪先跑完，虛空裂縫接在後面",
          names[:2] == ["自動日常雜務", "虛空裂縫"], str(names))

    print("\n全部通過。" if ok else "\n有項目未通過。")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
