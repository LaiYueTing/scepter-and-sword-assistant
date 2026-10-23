# -*- coding: utf-8 -*-
"""一輪中途出錯之後要重新連線、重試這一輪：

    python tests/test_retry_after_failure.py

⚠ 實機炸出來的：副本打到第三場時截圖逾時（模擬器一時沒有回應），整輪中斷，而排程
  直接去等下一個時刻——那天的領獎次數一次都沒用掉。更糟的是遊戲重開後會回到那張沒領的
  結算頁，後面的雜務與每日活動都卡在它的退出確認框上。

⚠ selftest 涵蓋不到：這裡驗的是一輪結束之後排程怎麼決定下一個跑誰。

測試把 Engine 與 Device 換成假的，不會碰到模擬器也不會操作遊戲。
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ⚠ 測試不能寫進真正的 assistant.log，要在 import core 之前設定。
os.environ.setdefault("SSA_LOG_DIR", tempfile.mkdtemp(prefix="ssa-test-log-"))

import core.runner as runner_mod
from core.adb import AdbError
from core.config import Config, TaskConfig

ok = True


def check(name: str, passed: bool, detail: str = "") -> None:
    global ok
    ok &= bool(passed)
    print(f"  [{'通過' if passed else '失敗'}] {name}" + (f"　{detail}" if detail else ""))


class FakeEngine:
    """前 `fail_times` 輪丟 AdbError，之後正常結束。"""

    runs = 0
    fail_times = 0

    def __init__(self, device, script, repeat=0, dry_run=False,
                 stop_event=None, status_hook=None):
        self.completed = 0
        self.yielded = False

    def reset(self) -> None:
        self.completed = 0

    def run(self, until=None) -> None:
        FakeEngine.runs += 1
        if FakeEngine.runs <= FakeEngine.fail_times:
            raise AdbError("模擬器沒有回應：adb exec-out screencap 超過 20 秒")
        self.completed = 1


class FakeDevice:
    connects = 0
    fail_reconnect = False

    def __init__(self, cfg):
        pass

    def connect(self):
        FakeDevice.connects += 1
        if FakeDevice.fail_reconnect and FakeDevice.connects > 1:
            raise AdbError("無法連線")


def run(fail_times: int, fail_reconnect: bool = False) -> int:
    """只有一份不排時間的副本：啟動先跑它，佇列清空就結束。回傳副本跑了幾次。"""
    FakeEngine.runs, FakeEngine.fail_times = 0, fail_times
    FakeDevice.connects, FakeDevice.fail_reconnect = 0, fail_reconnect
    cfg = Config(path=Path("x"))
    cfg.device.serial = "auto"
    cfg.tasks = [TaskConfig(name="dungeon", enabled=True, daily_at=[], repeat=0)]
    saved = runner_mod.Engine, runner_mod.Device, runner_mod.RETRY_DELAY
    runner_mod.Engine, runner_mod.Device, runner_mod.RETRY_DELAY = FakeEngine, FakeDevice, 0
    try:
        runner_mod.Runner(cfg, cfg.tasks).run()
    finally:
        runner_mod.Engine, runner_mod.Device, runner_mod.RETRY_DELAY = saved
    return FakeEngine.runs


def main() -> int:
    limit = runner_mod.RETRY_LIMIT

    print("出錯一次 → 重新連線後重試，第二次成功")
    n = run(fail_times=1)
    check("跑了兩次", n == 2, f"跑了 {n} 次")
    check("重新連線過", FakeDevice.connects == 2, f"連線 {FakeDevice.connects} 次")

    print("一直出錯 → 重試到上限就放掉")
    n = run(fail_times=99)
    check(f"跑了 1 + {limit} 次", n == 1 + limit, f"跑了 {n} 次")

    print("重試成功之後失敗次數歸零")
    n = run(fail_times=limit)
    check(f"出錯 {limit} 次之後第 {limit + 1} 次成功", n == limit + 1, f"跑了 {n} 次")

    print("重新連線失敗 → 不重試")
    n = run(fail_times=1, fail_reconnect=True)
    check("只跑一次", n == 1, f"跑了 {n} 次")

    print("沒有出錯 → 不重試")
    n = run(fail_times=0)
    check("只跑一次", n == 1, f"跑了 {n} 次")

    print("\n全部通過。" if ok else "\n有項目未通過。")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
