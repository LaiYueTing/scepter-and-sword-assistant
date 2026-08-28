# -*- coding: utf-8 -*-
"""讓位的腳本要被排回去接著跑：

    python tests/test_yield_requeue.py

引擎在 `count:` 那一刻若發現已經到了下一個排定時刻，就會收工讓位。讓位代表
**該做的還沒做完**（次數還有、獎勵還沒領），所以排程要把它排回佇列。

⚠ 這條路 selftest 涵蓋不到——那支是一張畫面一張畫面地驗規則，而這裡驗的是
  一輪跑完之後排程怎麼決定下一個跑誰。

⚠ 這是實機炸出來的：另一位使用者 08:30 開打副本，09:04 拿到第一次 S、領完獎，
  剛好撞上 09:00 的排程而讓位——第二次領獎次數就一路留到隔天，而紀錄上每一行
  都正常。修好之前沒有任何測試會紅。

測試把 Engine 換成假的，不會碰到模擬器也不會操作遊戲。
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ⚠ **測試不能寫進真正的 assistant.log。** 那是使用者用來監督執行狀況的檔案，
#   混進假的排程與假的下載失敗比沒有紀錄更糟。要在 import core 之前設定。
os.environ.setdefault("SSA_LOG_DIR", tempfile.mkdtemp(prefix="ssa-test-log-"))

import core.runner as runner_mod
from core.config import Config, TaskConfig

ok = True


def check(name: str, passed: bool, detail: str = "") -> None:
    global ok
    ok &= bool(passed)
    print(f"  [{'通過' if passed else '失敗'}] {name}" + (f"　{detail}" if detail else ""))


class FakeEngine:
    """記錄自己被跑過幾次，並照劇本決定這一輪是不是「讓位」收場。"""

    runs: list[str] = []

    def __init__(self, device, script, repeat=0, dry_run=False,
                 stop_event=None, status_hook=None):
        self.script = script
        self.completed = 0
        self.yielded = False
        self._stop_event = stop_event

    def reset(self) -> None:
        self.completed = 0
        self.yielded = False

    def run(self, until=None) -> None:
        name = self.script.name
        FakeEngine.runs.append(name)
        self.completed = 1
        # 副本第一次跑「讓位」收場，之後正常收工
        self.yielded = name == "自動副本" and FakeEngine.runs.count(name) == 1
        # 收工條件：副本跑到第二次（＝被排回來了），或雜務已經跑過一輪。
        # ⚠ 少了後半，關掉補跑的那一輪會停在「等下一個排定時刻」上——那是 24
        #   小時後，測試就掛在那裡不動了。
        if (FakeEngine.runs.count("自動副本") >= 2
                or name == "自動日常雜務" or len(FakeEngine.runs) >= 3):
            if self._stop_event is not None:
                self._stop_event.set()


class FakeDevice:
    def __init__(self, cfg):
        pass

    def connect(self):
        return None


def build_runner(catch_up: bool = True) -> runner_mod.Runner:
    """兩個腳本：副本（現在起跑）與雜務（一分鐘後）。"""
    now = datetime.now()
    soon = (now + timedelta(minutes=1)).strftime("%H:%M")
    cfg = Config(path=Path("x"))
    cfg.device.serial = "auto"          # describe_setup() 會去讀，沒填會拋設定錯誤
    cfg.runtime.catch_up = catch_up
    cfg.runtime.catch_up_guard_minutes = 0        # 不要讓「快到了」的讓路擋住測試
    # 副本刻意**不排時間**：它只會以「啟動先跑清單第一個」的身分跑一次，
    # 所以之後再出現就一定是被排回去的那一次，不會和排程混在一起。
    cfg.tasks = [
        TaskConfig(name="dungeon", enabled=True, daily_at=[], repeat=0),
        TaskConfig(name="chores", enabled=True, daily_at=[soon], repeat=1),
    ]
    return runner_mod.Runner(cfg, cfg.tasks)


def run_once(catch_up: bool = True) -> list[str]:
    FakeEngine.runs = []
    real_engine, real_device = runner_mod.Engine, runner_mod.Device
    runner_mod.Engine, runner_mod.Device = FakeEngine, FakeDevice
    try:
        build_runner(catch_up).run()
    finally:
        runner_mod.Engine, runner_mod.Device = real_engine, real_device
    return FakeEngine.runs


def main() -> int:
    print("讓位之後有沒有被排回來")
    runs = run_once(catch_up=True)
    print(f"    實際跑的順序：{runs}")
    check("副本跑了兩次（讓位那次 ＋ 排回來那次）",
          runs.count("自動副本") == 2, f"跑了 {runs.count('自動副本')} 次")

    print("關掉補跑就不排回去")
    runs = run_once(catch_up=False)
    print(f"    實際跑的順序：{runs}")
    check("副本只跑一次", runs.count("自動副本") == 1,
          f"跑了 {runs.count('自動副本')} 次")

    print("\n全部通過。" if ok else "\n有項目未通過。")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
