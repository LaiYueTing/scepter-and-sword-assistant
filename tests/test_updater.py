"""驗自動更新裡「換掉執行中的執行檔」這件事真的成立。

⚠ 這條路 `selftest` 涵蓋不到——那支是拿樣本圖驗規則的，而這裡驗的是作業系統的
  檔案語意。也不能只靠讀程式碼判斷：Windows 允許改名執行中的 EXE、卻不允許覆寫它，
  整個換檔手法就建立在這個差別上，所以要當場量。

用 `PING.EXE` 當替身（自帶會阻塞的參數、不需要任何相依檔案），
不必為了測試去編一份一百多 MB 的 EXE。

    python tests/test_updater.py
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ⚠ **測試不能寫進真正的 assistant.log。** 那是使用者用來監督執行狀況的檔案，
#   混進假的排程與假的下載失敗比沒有紀錄更糟。要在 import core 之前設定。
os.environ.setdefault("SSA_LOG_DIR", tempfile.mkdtemp(prefix="ssa-test-log-"))

from core import updater

ok = True


def check(label: str, passed: bool, detail: str = "") -> None:
    global ok
    ok &= passed
    print(f"  [{'通過' if passed else '失敗'}] {label}"
          + (f"　{detail}" if detail else ""))


def test_version_compare() -> None:
    print("版本比大小")
    check("新版比得出來", updater.is_newer("1.0.92.0", "1.0.91.0"))
    check("同版不算新", not updater.is_newer("1.0.91.0", "1.0.91.0"))
    check("舊版不算新", not updater.is_newer("1.0.90.0", "1.0.91.0"))
    # 位數不一樣時要補齊再比，否則 1.0.92 會被判成小於 1.0.92.0
    check("位數不同也對得起來", not updater.is_newer("1.0.91", "1.0.91.0"))
    check("v 前綴不影響", updater.is_newer("v1.1.0.0", "1.0.99.0"))
    check("認不出來的字串不會炸", not updater.is_newer("", "1.0.91.0"))


def test_swap() -> None:
    """改名 → 搬新檔 → 行程照活，這正是 `updater.apply()` 的三步。"""
    print("換掉執行中的執行檔")
    with tempfile.TemporaryDirectory() as tmp:
        here = Path(tmp)
        src = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "PING.EXE"
        if not src.is_file():
            check("找得到替身程式", False, str(src))
            return

        live, newer = here / "live.exe", here / "newer.exe"
        backup = live.with_name(live.name + ".old")
        shutil.copyfile(src, live)
        shutil.copyfile(src, newer)

        proc = subprocess.Popen([str(live), "-n", "60", "127.0.0.1"],
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
        try:
            time.sleep(2)
            if proc.poll() is not None:
                check("替身跑得起來", False)
                return

            try:
                os.replace(live, backup)
                check("執行中的 EXE 改得了名", True)
            except OSError as e:
                check("執行中的 EXE 改得了名", False, str(e))
                return

            try:
                os.replace(newer, live)
                check("新檔搬得進原本的位置", True)
            except OSError as e:
                check("新檔搬得進原本的位置", False, str(e))
                os.replace(backup, live)      # apply() 的回復路徑
                return

            check("換檔期間行程仍活著", proc.poll() is None)

            # 反向驗證：直接覆寫會失敗，這正是「非得先改名不可」的理由
            try:
                shutil.copyfile(src, backup)
                check("直接覆寫執行中的 EXE 會失敗", False, "竟然成功了")
            except OSError:
                check("直接覆寫執行中的 EXE 會失敗", True)
        finally:
            proc.kill()
            proc.wait()

        time.sleep(0.5)
        original, updater.ROOT = updater.ROOT, here
        try:
            updater.cleanup()
        finally:
            updater.ROOT = original
        check("cleanup() 清掉 .old", not backup.exists())



# 這段會被寫成一支獨立的腳本執行：`restart()` 的重點是「母行程結束**之後**」
# 才動作，同一個行程裡驗不到。
_PROBE = """
import os, subprocess, sys
target, marker = sys.argv[1], sys.argv[2]
flags = int(sys.argv[3])
script = ("Wait-Process -Id %d -ErrorAction SilentlyContinue; "
          "Start-Sleep -Milliseconds 600; "
          "Start-Process -FilePath '%s' -WindowStyle Hidden" % (os.getpid(), target))
subprocess.Popen(["powershell", "-NoProfile", "-WindowStyle", "Hidden",
                  "-Command", script], creationflags=flags)
"""


def _try_flags(tmp: Path, name: str, flags: int) -> bool:
    """排一次「等我結束再啟動」，回傳替身有沒有真的被開起來。"""
    marker = tmp / f"m_{name}.txt"
    target = tmp / f"t_{name}.cmd"
    probe = tmp / f"probe_{name}.py"
    marker.unlink(missing_ok=True)
    # ⚠ 批次檔的換行用 os.linesep 組出來，不要在字串裡寫跳脫序列——
    #   這個檔案本身就會被工具改寫，跳脫序列在那個過程裡很容易被吃掉。
    target.write_text("@echo off" + os.linesep
                      + f'> "{marker}" echo ok' + os.linesep,
                      encoding="ascii")
    probe.write_text(_PROBE, encoding="utf-8")

    subprocess.run([sys.executable, str(probe), str(target), str(marker),
                    str(flags)], check=False, capture_output=True)
    for _ in range(24):                  # 母行程已結束，最多再等 12 秒
        if marker.exists():
            return True
        time.sleep(0.5)
    return False


def test_restart_flags() -> None:
    """`restart()` 的 creationflags 只能給 CREATE_NO_WINDOW。

    ⚠ 這不是潔癖：`DETACHED_PROCESS` 會讓那個 PowerShell 當場死掉，而
      `Popen` 不報錯、PID 也拿得到——症狀是「更新完就再也開不起來」，
      從程式碼上完全看不出來。
    """
    print("重新啟動的排程手法")
    no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    detached = getattr(subprocess, "DETACHED_PROCESS", 0)
    with tempfile.TemporaryDirectory() as tmp:
        here = Path(tmp)
        check("CREATE_NO_WINDOW 排得起來", _try_flags(here, "nowindow", no_window))
        check("DETACHED_PROCESS 排不起來（所以不能用）",
              not _try_flags(here, "detached", detached))


def test_restart_env_scrubbed() -> None:
    """重新啟動時傳出去的環境變數不能帶著 PyInstaller 的私有那幾個。

    ⚠ 這是實機炸出來的，而且**每次都炸**：bootloader 靠
      `_PYI_PARENT_PROCESS_LEVEL` / `_PYI_APPLICATION_HOME_DIR` 認出「我是已經
      解壓好的子行程」，繼承下去的話新版會跳過解壓、去載入舊版早就刪掉的目錄，
      使用者看到 `Failed to load Python DLL ... LoadLibrary: 找不到指定的模組`。
      雙擊不會有事，所以只有更新後的重新啟動會遇到。
    """
    print("重新啟動時的環境變數")
    keep = dict(os.environ)
    os.environ["_PYI_APPLICATION_HOME_DIR"] = r"C:\Temp\_MEI999992"
    os.environ["_PYI_PARENT_PROCESS_LEVEL"] = "1"
    os.environ["_MEIPASS2"] = r"C:\Temp\_MEI999992"
    os.environ["SSA_TEST_KEEPME"] = "1"
    try:
        env = updater._clean_env()
    finally:
        os.environ.clear()
        os.environ.update(keep)
    leaked = sorted(k for k in env
                    if k.startswith("_PYI_") or k == "_MEIPASS2")
    check("_PYI_* 與 _MEIPASS2 都清掉了", not leaked, f"漏了 {leaked}" if leaked else "")
    check("其餘環境變數照抄", env.get("SSA_TEST_KEEPME") == "1")


class _FakeResponse:
    """假的 HTTP 回應。`body` 給多少就回多少，`declared` 是 Content-Length。"""

    def __init__(self, body: bytes, declared: int):
        self._body = body
        self._at = 0
        # 200 而不是 206：這個假回應不支援分段，download() 會走單線那條路，
        # 而這支測試要驗的正是「單線抓完之後的完整性檢查」。
        self.status = 200
        self.headers = {"Content-Length": str(declared)}

    def read(self, n: int = -1) -> bytes:
        chunk = self._body[self._at:] if n < 0 else self._body[self._at:self._at + n]
        self._at += len(chunk)
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _download_with(body: bytes, declared: int, tmp: Path):
    """把 urlopen 換成假的，跑一次 download()，回傳它給的路徑。"""
    import urllib.request

    class R:
        version = "9.9.9.9"
        tag = "v9.9.9.9"
        title = "t"
        notes = ""
        url = "https://example.invalid/x.exe"
        size = declared
        size_text = "x"

    real_open, real_root = urllib.request.urlopen, updater.ROOT
    urllib.request.urlopen = lambda *a, **k: _FakeResponse(body, declared)
    updater.ROOT = tmp
    try:
        return updater.download(R())
    finally:
        urllib.request.urlopen, updater.ROOT = real_open, real_root


def test_download_verification() -> None:
    """截斷的下載不能被當成完成。

    ⚠ 這是實機炸出來的，而且後果是永久的：`resp.read()` 在連線半途斷掉時回傳
      空字串，`while` 迴圈就正常結束——沒有例外。少了驗證，一個截斷的 EXE 會被
      換上去，使用者從此每次啟動都看到「Failed to load Python DLL」。
    """
    print("下載完整性")
    with tempfile.TemporaryDirectory() as tmp:
        here = Path(tmp)
        whole = b"MZ" + bytes(4094)      # 假的執行檔：檔頭對、長度固定
        check("完整的下載會收下", _download_with(whole, len(whole), here) is not None)
        check("截斷的下載要拒絕",
              _download_with(whole[:3000], len(whole), here) is None)
        check("不是執行檔的內容要拒絕",
              _download_with(b"<html>rate limited</html>",
                             len(b"<html>rate limited</html>"), here) is None)
        leftovers = [p.name for p in here.iterdir() if p.suffix == ".part"]
        check("失敗時不留半成品", not leftovers, str(leftovers))



def test_sweep_temp() -> None:
    """清暫存殘骸只能碰「確定是我們的、而且沒被鎖住」的那些。

    ⚠ 最重要的是最後一項：唯讀工具（doctor、selftest）不上防多開的鎖，可能正有
      一份在跑。忽略錯誤地刪下去會把它**刪成半殘**而當場炸掉，比不清還糟。
    """
    print("清暫存殘骸")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        frozen_before = getattr(sys, "frozen", False)
        sys.frozen = True
        sys._MEIPASS = str(root / "_MEIcurrent")

        mine = root / "_MEI111111"
        mine.mkdir()
        (mine / "config.example.yaml").touch()
        current = root / "_MEIcurrent"
        current.mkdir()
        (current / "config.example.yaml").touch()
        other = root / "_MEI222222"
        other.mkdir()
        (other / "someone_elses.txt").touch()
        busy = root / "_MEI333333"
        busy.mkdir()
        (busy / "config.example.yaml").touch()
        held = (busy / "in_use.dll").open("wb")     # 假裝有行程正在用

        real = updater.tempfile.gettempdir
        updater.tempfile.gettempdir = lambda: str(root)
        try:
            swept = updater.sweep_temp()
        finally:
            updater.tempfile.gettempdir = real
            held.close()
            if not frozen_before:
                del sys.frozen

        check("自己的殘骸清得掉", not mine.exists())
        check("目前這一份不會被誤刪", current.exists())
        check("別的程式的不要碰", other.exists())
        check("鎖住的整個跳過，不會刪成半殘",
              busy.exists() and (busy / "config.example.yaml").exists())
        check("回報清掉的數量", swept == 1, f"回報 {swept}")


def test_backup_path_when_old_is_stuck() -> None:
    """`.old` 還被佔著的時候，備份要換一個名字，不要在同一個路徑上硬碰硬。

    這是 2026-08-30 使用者回報的 [WinError 5]：更新按下去只說「換不掉舊版：
    存取被拒」，而真正卡住的是那個誰都看不到的 `.old`——上一版的行程還開著
    （工作管理員裡是兩個處理程序），或者防毒正握著它。

    ⚠ 兩種成因都要驗：**被別的行程開著**與**唯讀屬性**，實測都是同一個
      WinError 5。
    """
    print("備份路徑（.old 卡住時）")
    with tempfile.TemporaryDirectory() as tmp:
        here = Path(tmp)
        cur = here / "ScepterSwordAssistant.exe"
        cur.write_bytes(b"MZ" + b"x" * 64)
        old = cur.with_name(cur.name + ".old")

        check("沒有 .old 時就用原本的名字",
              updater._spare_backup(cur).name == cur.name + ".old")

        old.write_bytes(b"stale")
        check("有 .old 但沒人佔著時照樣用原本的名字",
              updater._spare_backup(cur).name == cur.name + ".old")

        old.write_bytes(b"stale")
        holder = open(old, "rb")            # 上一版的行程還開著
        try:
            picked = updater._spare_backup(cur)
            check("被佔著時換一個名字", picked != old, picked.name)
            check("換出來的名字帶時間戳",
                  bool(re.search(r"\.exe\.\d{14}\.old$", picked.name)),
                  picked.name)
            try:
                os.replace(cur, picked)
                check("用新名字真的搬得動", True)
            except OSError as e:
                check("用新名字真的搬得動", False, str(e))
        finally:
            holder.close()

        # 唯讀是另一個成因，實測同樣是 WinError 5
        cur.write_bytes(b"MZ" + b"x" * 64)
        old.write_bytes(b"stale")
        os.chmod(old, stat.S_IREAD)
        try:
            picked = updater._spare_backup(cur)
            check("唯讀的 .old 也要換名字", picked != old, picked.name)
        finally:
            os.chmod(old, stat.S_IWRITE)


def test_cannot_apply_from_source() -> None:
    """從原始碼跑的時候要明講「換不了」，不要默默做出一個壞掉的 EXE。"""
    print("執行環境判斷")
    can, why = updater.can_apply()
    check("未打包時拒絕換檔", not can and bool(why), why)


def main() -> int:
    test_version_compare()
    test_swap()
    test_restart_flags()
    test_restart_env_scrubbed()
    test_download_verification()
    test_sweep_temp()
    test_backup_path_when_old_is_stuck()
    test_cannot_apply_from_source()
    print("\n全部通過。" if ok else "\n有項目未通過。")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
