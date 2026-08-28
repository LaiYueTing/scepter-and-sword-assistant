"""發版前的關卡：原始碼、打包出來的 EXE、GitHub 上的版本，三邊要對得起來。

跑法：

    python tools/release_check.py                                 # 只驗原始碼
    python tools/release_check.py --exe "dist/杖劍傳說助手.exe"    # 連打包產物一起驗

⚠ **要在 gh release create 之前跑，而且要全綠才發。** 這支存在的理由是
  v1.0.6～v1.0.8 連續三版帶著問題出去：截斷的下載被當成完成、重新啟動時
  PyInstaller 的私有環境變數沒清掉、以及一個只有按下「開始執行」才碰得到的
  import 錯誤。每一個都在打包之後、發布之前跑一次就會現形。

各項檢查對應的失敗形狀：

  版本號三處一致    對不上的話助手會回報舊版本，別人的更新器於是永遠停不下來
  工作區乾淨        發出去的 EXE 和版控裡的原始碼不是同一份
  tests/ 全過       跨執行的狀態、排程、更新換檔，selftest 結構上都驗不到
  selftest          模板或規則被改壞
  EXE 的版本資源    .spec 讀的是 assets/version_info.txt，忘了 bump 就會不一致
  EXE 內建的模組    原始碼有、PyInstaller 沒收進去（延後匯入最容易漏）
  EXE 內建的資源    少了 gui/web 就是一片空白頁，少了 templates 就什麼都認不得
  EXE 跑得起來      這是唯一驗得到「這顆檔案本身沒壞」的方法
  版本比線上的新    發一個不比線上新的版本，等於沒有人會收到更新
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

REPO = "LaiYueTing/scepter-and-sword-assistant"

failures: list[str] = []


def check(ok: bool, name: str, detail: str = "") -> bool:
    print(f"  [{'通過' if ok else '失敗'}] {name}" + (f"　{detail}" if detail else ""))
    if not ok:
        failures.append(name)
    return ok


def check_versions() -> str:
    """版本號：core/config.py 的 VERSION 是真相，version_info 的四欄要跟著它。

    ⚠ 版本號是 X.Y.Z，而 **Windows 的 `filevers` / `prodvers` 規定四個數字**，
      末位固定補 0。所以那兩欄比對的是 `X.Y.Z.0`，字串欄位才比 `X.Y.Z`。
    """
    print("版本號")
    m = re.search(r'^VERSION\s*=\s*"(\d+\.\d+\.\d+)"',
                  (ROOT / "core" / "config.py").read_text(encoding="utf-8"), re.M)
    ver = m.group(1) if m else ""

    text = (ROOT / "assets" / "version_info.txt").read_text(encoding="utf-8")
    found = {}
    for key in ("filevers", "prodvers"):
        t = re.search(key + r"=\((\d+),\s*(\d+),\s*(\d+),\s*(\d+)\)", text)
        found[key] = (".".join(t.groups()) if t else "", ver + ".0")
    for key in ("FileVersion", "ProductVersion"):
        f = re.search(key + r"',\s*'([\d.]+)'", text)
        found[key] = (f.group(1) if f else "", ver)

    bad = sorted(f"{k}={got or '?'}" for k, (got, want) in found.items() if got != want)
    check(bool(ver) and not bad, "版本號四處一致",
          f"v{ver}" + (f"，對不上：{bad}" if bad else ""))
    return ver


def check_worktree() -> None:
    print("\n版控")
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                           capture_output=True, text=True).stdout.strip()
    check(not dirty, "工作區乾淨",
          "" if not dirty else f"{len(dirty.splitlines())} 個檔案還沒提交")

    r = subprocess.run(["git", "rev-list", "--count", "origin/main..HEAD"],
                       cwd=ROOT, capture_output=True, text=True)
    ahead = r.stdout.strip()
    check(ahead == "0", "本機和 origin/main 同步",
          "" if ahead == "0" else f"還有 {ahead} 個 commit 沒推上去")


def check_tests(skip_selftest: bool) -> None:
    print("\n測試")
    for path in sorted((ROOT / "tests").glob("test_*.py")):
        p = subprocess.run([sys.executable, str(path)], cwd=ROOT,
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        tail = [ln for ln in (p.stdout or "").splitlines() if ln.strip()]
        check(p.returncode == 0, path.name,
              "" if p.returncode == 0 else (tail[-1] if tail else "沒有輸出"))

    if skip_selftest:
        print("  [略過] selftest（--skip-selftest）")
        return
    if not (ROOT / "samples").is_dir():
        print("  [略過] selftest（這份 clone 沒有 samples/）")
        return
    p = subprocess.run([sys.executable, "main.py", "selftest"], cwd=ROOT,
                       capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    tail = [ln for ln in (p.stdout or "").splitlines() if ln.strip()]
    check(p.returncode == 0, "selftest", tail[-1] if tail else "")


def check_exe(exe: Path, ver: str) -> None:
    print(f"\n打包產物　{exe.name}　{exe.stat().st_size / 1048576:.0f} MB")

    # ⚠ 打包鏈接好了不等於打包過了。實測拿過一顆「TOC 裡 webview / gui 全部是 0」
    #   的 EXE——它是在那些改動之前編的，而從原始碼上完全看不出來。
    sources = [ROOT / "main.py", ROOT / "杖劍傳說助手.spec"]
    for d in ("core", "gui", "scripts", "assets"):
        sources += [p for p in (ROOT / d).rglob("*")
                    if p.is_file() and "__pycache__" not in p.parts]
    mtime, newest = max((p.stat().st_mtime, p) for p in sources if p.is_file())
    stale = exe.stat().st_mtime < mtime
    check(not stale, "EXE 比原始碼新",
          f"{newest.relative_to(ROOT)} 比 EXE 還新，要重編" if stale else "")

    ps = "(Get-Item -LiteralPath '" + str(exe) + "').VersionInfo.FileVersion"
    got = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
        capture_output=True, text=True).stdout.strip()
    check(got == ver, "EXE 的版本資源和原始碼一致", f"EXE 是 v{got}")

    from PyInstaller.archive.readers import CArchiveReader, ZlibArchiveReader

    reader = CArchiveReader(str(exe))
    names = [n.replace("\\", "/") for n in reader.toc]

    def has(prefix: str) -> int:
        return sum(1 for n in names if n.startswith(prefix))

    want = {
        "gui/web/index.html": 1,
        "scripts/": len(list((ROOT / "scripts").glob("*.yaml"))),
        "templates/": len(list((ROOT / "templates").glob("*.png"))),
        "platform-tools/adb.exe": 1,
        "config.example.yaml": 1,
    }
    missing = [f"{k}（{has(k)}/{n}）" for k, n in want.items() if has(k) < n]
    check(not missing, "內建的資源齊全",
          "、".join(missing) if missing
          else f"腳本 {has('scripts/')} 份、模板 {has('templates/')} 張")

    # ⚠ 這一項是為 v1.0.8.0 那次加的：gui/runner.py 要按下「開始執行」才會被載入，
    #   原始碼層的 import 掃描抓得到寫錯的 import，卻抓不到「PyInstaller 根本沒把
    #   這個模組收進去」——那要去看 EXE 裡的 PYZ 才知道。
    blob = reader.extract("PYZ.pyz")
    if isinstance(blob, tuple):
        blob = blob[-1]
    tmp = Path(tempfile.mkdtemp(prefix="ssa-pyz-")) / "PYZ.pyz"
    tmp.write_bytes(blob)
    inside = {m for m in ZlibArchiveReader(str(tmp)).toc
              if m.split(".")[0] in ("core", "gui")}

    expected = {"core", "gui"}
    for pkg in ("core", "gui"):
        for py in (ROOT / pkg).glob("*.py"):
            if py.stem not in ("__init__", "__main__"):
                expected.add(pkg + "." + py.stem)
    absent = sorted(expected - inside)
    check(not absent, "內建的模組齊全",
          f"{len(inside)} 個" + (f"，缺：{absent}" if absent else ""))

    # ⚠ 紀錄要導去暫存目錄。這一步會真的執行 EXE，而使用者平常就在 dist 裡跑它，
    #   不隔離的話這幾行會混進他用來監督執行狀況的 assistant.log。
    env = dict(os.environ)
    env["SSA_LOG_DIR"] = tempfile.mkdtemp(prefix="ssa-relcheck-")
    p = subprocess.run([str(exe), "update", "--check"], cwd=exe.parent,
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=300, env=env)
    said = re.search(r"目前版本：v([\d.]+)", p.stdout or "")
    check(bool(said) and said.group(1) == ver, "EXE 跑得起來並回報正確版本",
          f"回報 v{said.group(1)}" if said
          else f"沒有回報版本（exit {p.returncode}）")


def check_newer_than_online(ver: str) -> None:
    print("\nGitHub")
    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{REPO}/releases/latest",
            headers={"User-Agent": "release-check"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            tag = json.load(resp).get("tag_name", "").lstrip("v")
    except Exception as e:
        print(f"  [略過] 查不到線上版本（{type(e).__name__}）")
        return

    # ⚠ **比大小要用更新器自己那一份**（它會把兩邊補到一樣長，`1.0.0` 和 `1.0.0.0`
    #   才不會被判成一大一小）。在這裡另外寫一份的話，關卡說「可以發」而使用者的
    #   更新器說「沒有新版」——兩份實作只要差一點，症狀就是這種對不起來。
    from core import updater

    newer = updater.is_newer(ver, tag)
    check(newer, "要發的版本比線上的新",
          f"線上 v{tag} → 要發 v{ver}" if newer
          else f"線上已經是 v{tag}，還沒遞增版本號（tools/bump_version.py）")


def main() -> int:
    ap = argparse.ArgumentParser(description="發版前的完整檢查")
    ap.add_argument("--exe", help="要一起驗的打包產物")
    ap.add_argument("--skip-selftest", action="store_true", help="不跑 selftest")
    args = ap.parse_args()

    print("發版前檢查\n")
    ver = check_versions()
    check_worktree()
    check_tests(args.skip_selftest)

    if args.exe:
        exe = Path(args.exe)
        if exe.is_file():
            check_exe(exe, ver)
        else:
            check(False, "找得到打包產物", str(exe))
    else:
        print("\n[略過] 打包產物（要一起驗就加 --exe）")

    check_newer_than_online(ver)

    print()
    if failures:
        print(f"[不要發布] {len(failures)} 項沒過：" + "、".join(failures))
        return 1
    print(f"[可以發布] v{ver} 全部通過")
    return 0


if __name__ == "__main__":
    sys.exit(main())
