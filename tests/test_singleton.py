# -*- coding: utf-8 -*-
"""core/singleton.py 的回歸測試：

    python tests/test_singleton.py

驗四件事：別的行程握著就拿不到、同一個行程重複取會拿到同一把、
門在取得鎖的當下就開、沒有視窗的（命令列的 run）敲不到。

⚠ 要真的開子行程：mutex 是 kernel 物件，同一個行程測不出互斥。
"""
import subprocess
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ⚠ 測試不寫進真正的 assistant.log，要在 import core 之前設定。
os.environ.setdefault("SSA_LOG_DIR", tempfile.mkdtemp(prefix="ssa-test-log-"))

from core import singleton

ok = True


class Busy(RuntimeError):
    """機器上已有助手握著鎖，這一輪無法測試。"""


def check(name: str, passed: bool) -> bool:
    global ok
    print(f"  [{'通過' if passed else '失敗'}] {name}")
    ok &= passed
    return passed


HOLDER = """\
import sys, time
sys.path.insert(0, {root!r})
from core import singleton
lock = singleton.acquire(windowed={listen})
if lock is None:
    print("NOLOCK", flush=True)
    raise SystemExit(1)
print("READY", flush=True)
if {listen}:
    # 刻意慢半拍才接回呼：模擬「鎖已經拿到、視窗還在建」那幾秒
    time.sleep({delay})
    lock.listen(lambda: print("WOKE", flush=True))
    print("LISTENING", flush=True)
sys.stdin.readline()
"""


def start_holder(listen: bool, delay: float = 0.0) -> subprocess.Popen:
    """開一個握著鎖的子行程，等它就緒才回來。

    `listen=False` 模擬命令列的 run：那一種沒有視窗，所以不開門。
    """
    p = subprocess.Popen(
        [sys.executable, "-c",
         HOLDER.format(root=str(ROOT), listen=listen, delay=delay)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        text=True, encoding="utf-8",
    )
    first = p.stdout.readline().strip()
    if first == "NOLOCK":
        # 環境忙碌，不是測試失敗：鎖是整台機器共用的。
        p.wait(timeout=10)
        raise Busy()
    assert first == "READY", f"子行程沒有就緒：{first!r}"
    return p


def stop_holder(p: subprocess.Popen) -> str:
    """讓子行程結束，回傳它剩下的輸出。"""
    p.stdin.write("\n")
    p.stdin.close()
    out = p.stdout.read()
    p.wait(timeout=10)
    return out


try:
    print("=== 1. 別的行程握著就拿不到 ===")
    holder = start_holder(listen=True)
    check("第二個實例取不到鎖", singleton.acquire() is None)

    print("=== 2. 敲得到既有實例 ===")
    check("wake_existing 回報敲到了", singleton.wake_existing() is True)
    time.sleep(0.5)
    check("既有實例真的醒了", "WOKE" in stop_holder(holder))

    print("=== 3. 對方結束後就拿得回來 ===")
    lock = singleton.acquire(windowed=True)
    check("鎖釋放了", lock is not None)

    print("=== 4. 同一個行程重複取是同一把（不會自己擋自己）===")
    check("兩層呼叫拿到同一把", singleton.acquire(windowed=True) is lock)

    print("=== 5. 自己握著時，別的行程進不來 ===")
    probe = subprocess.run(
        [sys.executable, "-c",
         f"import sys; sys.path.insert(0, {str(ROOT)!r});"
         " from core import singleton;"
         " print('GOT' if singleton.acquire() else 'BLOCKED')"],
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    check("子行程被擋下", probe.stdout.strip() == "BLOCKED")
    lock.release()

    print("=== 6. 沒有視窗的那一種要敲不到 ===")
    # 命令列的 run 不開門，第二個實例敲不到。
    holder = start_holder(listen=False)
    check("wake_existing 回報敲不到", singleton.wake_existing(0.4) is False)
    stop_holder(holder)

    print("=== 7. 連續雙擊：對方還在建視窗時就敲得到門 ===")
    # 門在取得鎖的當下就開，回呼接上之前的敲門會補叫。
    holder = start_holder(listen=True, delay=2.5)
    started = time.monotonic()
    check("回呼還沒接上就敲得到", singleton.wake_existing() is True)
    check("不必等對方載完（沒有卡住）", time.monotonic() - started < 1.5)
    out = stop_holder(holder)
    check("回呼接上時把那一次補叫出來", "WOKE" in out)
    # listen() 是在自己內部就補叫的，所以 WOKE 必定早於它的下一行
    check("一接上就補叫，不是拖到之後", "LISTENING" in out
          and out.index("WOKE") < out.index("LISTENING"))

    print("\n" + ("全部通過" if ok else "有失敗項目"))
except Busy:
    # 鎖被助手握著時回報「略過」。
    print("")
    print("[略過] 這台機器上已經有一個助手在執行中，鎖被握著就測不了。")
    print("       關掉助手（或等排程那一輪跑完）再跑一次。")
    sys.exit(0)
sys.exit(0 if ok else 1)
