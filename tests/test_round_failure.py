# -*- coding: utf-8 -*-
"""一輪發生例外時排程要繼續，而且要留下紀錄：

    python tests/test_round_failure.py

測試把 Engine 與 Device 換成假的，不會碰到模擬器也不會操作遊戲。
"""
import logging
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ⚠ 測試不寫進真正的 assistant.log，要在 import core 之前設定。
os.environ.setdefault("SSA_LOG_DIR", tempfile.mkdtemp(prefix="ssa-test-log-"))

import core.runner as runner_mod
from core.config import Config, TaskConfig

ok = True


def check(name: str, passed: bool, detail: str = "") -> None:
    global ok
    ok &= bool(passed)
    print(f"  [{'通過' if passed else '失敗'}] {name}" + (f"　{detail}" if detail else ""))


class ExplodingEngine:
    """第一輪丟出例外，之後正常結束本輪。"""

    runs: list[str] = []

    def __init__(self, device, script, repeat=0, dry_run=False,
                 stop_event=None, status_hook=None):
        self.script = script
        self.completed = 0
        self.yielded = False
        self._stop_event = stop_event

    def reset(self) -> None:
        self.completed = 0

    def run(self, until=None):
        ExplodingEngine.runs.append(self.script.name)
        if len(ExplodingEngine.runs) == 1:
            raise RuntimeError("模擬這一輪發生例外")
        if self._stop_event is not None:
            self._stop_event.set()      # 第二輪跑完就結束
        return 0


class FakeDevice:
    def __init__(self, cfg):
        pass

    def connect(self):
        return None


class Recorder(logging.Handler):
    """收集這次的紀錄。"""

    def __init__(self):
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record):
        self.lines.append(record.getMessage())
        if record.exc_info:
            self.lines.append("<traceback>")


def main() -> int:
    now = datetime.now()
    soon = (now + timedelta(minutes=1)).strftime("%H:%M")
    cfg = Config(path=Path("x"))
    cfg.device.serial = "auto"          # describe_setup() 會去讀
    cfg.runtime.catch_up_guard_minutes = 0
    # 副本不排時間，只以清單第一個的身分跑一次，那一次會丟例外。
    cfg.tasks = [
        TaskConfig(name="dungeon", enabled=True, daily_at=[], repeat=0),
        TaskConfig(name="chores", enabled=True, daily_at=[soon], repeat=1),
    ]

    states: list[tuple[str, str]] = []
    rec = Recorder()
    ExplodingEngine.runs = []
    real_engine, real_device = runner_mod.Engine, runner_mod.Device
    real_limit = runner_mod.RETRY_LIMIT
    runner_mod.Engine, runner_mod.Device = ExplodingEngine, FakeDevice
    # 驗放掉這一輪之後的路徑，重試關閉。重試見 test_retry_after_failure.py。
    runner_mod.RETRY_LIMIT = 0
    logging.getLogger().addHandler(rec)
    try:
        runner_mod.Runner(
            cfg, cfg.tasks,
            task_hook=lambda name, state, note: states.append((name, state)),
        ).run()
    finally:
        logging.getLogger().removeHandler(rec)
        runner_mod.Engine, runner_mod.Device = real_engine, real_device
        runner_mod.RETRY_LIMIT = real_limit

    print("發生例外的那一輪之後，排程要繼續")
    print(f"    實際跑的順序：{ExplodingEngine.runs}")
    check("第一輪發生例外，第二輪照樣執行", len(ExplodingEngine.runs) >= 2)

    print("紀錄要留得住，否則事後什麼都查不到")
    blob = "\n".join(rec.lines)
    check("寫得出「未預期的錯誤」", "未預期的錯誤" in blob)
    check("附上 traceback", "<traceback>" in blob)
    check("訊息裡看得到那個例外", "模擬這一輪發生例外" in blob)

    print("任務卡要轉紅，而且不能被「這一輪沒有完成」蓋回去")
    dungeon = [s for n, s in states if n == "dungeon"]
    check("出錯時轉紅", "error" in dungeon)
    # 出錯的文字不可與「這一輪沒有完成」相同。
    check("最後停在 error 而不是 done", dungeon[-1] == "error", f"實際：{dungeon}")
    print("介面那一層：失敗訊息不能被「待命中」蓋掉")
    from gui.runner import RunnerThread

    class SpyChannel:
        def __init__(self):
            self.sent: list[str] = []

        def send(self, event, data=None):
            self.sent.append(event)

    class Boom:
        def run(self):
            raise RuntimeError("模擬排程發生例外")

    spy = SpyChannel()
    th = RunnerThread.__new__(RunnerThread)
    th.channel, th.runner = spy, Boom()
    th.run()
    # failed 要排在 running=False 後面。
    check("running 先送、failed 後送", spy.sent == ["running", "failed"],
          f"實際：{spy.sent}")


    print("\n" + ("全部通過" if ok else "有失敗項目"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
