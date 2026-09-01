# -*- coding: utf-8 -*-
"""一輪炸掉不能把整個排程帶走，而且一定要留下紀錄：

    python tests/test_round_failure.py

⚠ selftest 涵蓋不到——那支是一張畫面一張畫面地驗規則，而這裡驗的是「某一輪
  丟出例外之後，排程還跑不跑得下去」。

⚠ 這是實機炸出來的（2026-09-01 08:00）：副本那一輪在第 27 秒消失，當天 09:00
  的雜務與 09:30 的每日活動全部沒有執行，而紀錄上只有一段 3 小時 57 分的空白。
  原因是 `Runner.run()` 只接 `AdbError`，別的例外一路冒到介面的背景執行緒，
  那裡把它送去狀態列就吞掉了——**連壞在哪裡都問不出來**。

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

# ⚠ 測試不能寫進真正的 assistant.log，要在 import core 之前設定。
os.environ.setdefault("SSA_LOG_DIR", tempfile.mkdtemp(prefix="ssa-test-log-"))

import core.runner as runner_mod
from core.config import Config, TaskConfig

ok = True


def check(name: str, passed: bool, detail: str = "") -> None:
    global ok
    ok &= bool(passed)
    print(f"  [{'通過' if passed else '失敗'}] {name}" + (f"　{detail}" if detail else ""))


class ExplodingEngine:
    """第一輪丟出例外，之後正常收工。"""

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
            raise RuntimeError("假裝這一輪炸了")
        if self._stop_event is not None:
            self._stop_event.set()      # 第二輪跑完就收工，不要停在等下一個時刻
        return 0


class FakeDevice:
    def __init__(self, cfg):
        pass

    def connect(self):
        return None


class Recorder(logging.Handler):
    """收下這次跑出來的紀錄，才驗得到「有沒有真的寫進去」。"""

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
    # 副本刻意不排時間：它只以「啟動先跑清單第一個」的身分跑一次，而那一次會炸。
    cfg.tasks = [
        TaskConfig(name="dungeon", enabled=True, daily_at=[], repeat=0),
        TaskConfig(name="chores", enabled=True, daily_at=[soon], repeat=1),
    ]

    states: list[tuple[str, str]] = []
    rec = Recorder()
    ExplodingEngine.runs = []
    real_engine, real_device = runner_mod.Engine, runner_mod.Device
    runner_mod.Engine, runner_mod.Device = ExplodingEngine, FakeDevice
    logging.getLogger().addHandler(rec)
    try:
        runner_mod.Runner(
            cfg, cfg.tasks,
            task_hook=lambda name, state, note: states.append((name, state)),
        ).run()
    finally:
        logging.getLogger().removeHandler(rec)
        runner_mod.Engine, runner_mod.Device = real_engine, real_device

    print("炸掉的那一輪之後，排程還跑不跑得下去")
    print(f"    實際跑的順序：{ExplodingEngine.runs}")
    check("第一輪炸了，第二輪照樣跑到", len(ExplodingEngine.runs) >= 2)

    print("紀錄要留得住，否則事後什麼都查不到")
    blob = "\n".join(rec.lines)
    check("寫得出「未預期的錯誤」", "未預期的錯誤" in blob)
    check("附上 traceback", "<traceback>" in blob)
    check("訊息裡看得到那個例外", "假裝這一輪炸了" in blob)

    print("任務卡要轉紅，而且不能被「這一輪沒有完成」蓋回去")
    dungeon = [s for n, s in states if n == "dungeon"]
    check("出錯時轉紅", "error" in dungeon)
    # ⚠ 「這一輪沒有完成」和「次數用盡就收工」長得一模一樣，蓋回去等於把出過事
    #   這件事從畫面上抹掉。
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
            raise RuntimeError("假裝排程整個炸了")

    spy = SpyChannel()
    th = RunnerThread.__new__(RunnerThread)
    th.channel, th.runner = spy, Boom()
    th.run()
    # ⚠ 介面收到 running=False 會把狀態列寫回「待命中」，所以 failed 一定要排在
    #   它後面，否則那句話活不過幾毫秒。
    check("running 先送、failed 後送", spy.sent == ["running", "failed"],
          f"實際：{spy.sent}")


    print("\n" + ("全部通過" if ok else "有失敗項目"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
