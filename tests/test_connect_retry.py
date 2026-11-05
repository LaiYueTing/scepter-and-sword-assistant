# -*- coding: utf-8 -*-
"""到點重新連線失敗時要重試，不能直接放掉那一格：

    python tests/test_connect_retry.py

測試把 Device 換成假的，不會碰到模擬器。
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ⚠ 測試不寫進真正的 assistant.log，要在 import core 之前設定。
os.environ.setdefault("SSA_LOG_DIR", tempfile.mkdtemp(prefix="ssa-test-log-"))

import core.runner as runner_mod
from core.adb import AdbError, Device
from core.config import Config, TaskConfig

ok = True


def check(name: str, passed: bool, detail: str = "") -> None:
    global ok
    ok &= bool(passed)
    print(f"  [{'通過' if passed else '失敗'}] {name}" + (f"　{detail}" if detail else ""))


class FlakyDevice:
    """前 fails 次連線失敗。"""

    def __init__(self, fails: int):
        self.fails, self.calls = fails, 0

    def connect(self) -> None:
        self.calls += 1
        if self.calls <= self.fails:
            raise AdbError("shell 失敗：wm size\nerror: closed\n")


def build_runner() -> runner_mod.Runner:
    cfg = Config(path=Path("x"))
    cfg.tasks = [TaskConfig(name="chores", repeat=1)]
    return runner_mod.Runner(cfg, cfg.tasks)


def test_runner_retries() -> None:
    runner_mod.CONNECT_RETRY_DELAY = 0
    r = build_runner()
    task = r.tasks[0]

    dev = FlakyDevice(fails=2)
    check("失敗兩次之後連上，這一格照跑", r._connect_with_retry(dev, task) and dev.calls == 3,
          f"連了 {dev.calls} 次")

    dev = FlakyDevice(fails=99)
    check("一直連不上才放掉", not r._connect_with_retry(dev, task)
          and dev.calls == runner_mod.CONNECT_RETRIES + 1, f"連了 {dev.calls} 次")

    r.stop_event.set()
    runner_mod.CONNECT_RETRY_DELAY = 60
    dev = FlakyDevice(fails=99)
    check("按下停止就不再重試", not r._connect_with_retry(dev, task) and dev.calls == 1,
          f"連了 {dev.calls} 次")


def test_device_reconnects_when_stale() -> None:
    """adb 回報在線，第一個指令才發現連線已失效：斷開重連。"""
    dev = Device.__new__(Device)
    dev.serial = "192.168.1.108:16480"
    log: list[str] = []
    dev._ensure_server = lambda: None
    dev._try_connect = lambda: log.append("connect")
    dev.is_online = lambda: True
    dev._disconnect = lambda: log.append("disconnect")

    def verify() -> None:
        log.append("verify")
        if log.count("verify") == 1:
            raise AdbError("shell 失敗：wm size\nerror: closed\n")

    dev._verify_spec = verify
    dev.connect()
    check("斷開重連之後再驗一次", log == ["connect", "verify", "disconnect", "connect", "verify"],
          " → ".join(log))


if __name__ == "__main__":
    test_runner_retries()
    test_device_reconnects_when_stale()
    print("全部通過" if ok else "有失敗")
    sys.exit(0 if ok else 1)
