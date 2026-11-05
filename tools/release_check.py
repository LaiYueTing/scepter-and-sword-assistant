"""發版前的檢查：原始碼、打包出來的 EXE、GitHub 上的版本三邊一致。

    python tools/release_check.py                                 # 只驗原始碼
    python tools/release_check.py --exe "dist/杖劍傳說助手.exe"    # 連打包產物一起驗

⚠ 在 gh release create 之前執行，全部通過才發布。

  版本號三處一致    core/config.py、version_info 的版本欄位
  工作區乾淨        EXE 與版控的原始碼是同一份
  tests/ 全過       排程、更新、跨執行狀態等 selftest 驗不到的項目
  selftest          模板與規則
  EXE 的版本資源    .spec 讀 assets/version_info.txt
  EXE 內建的模組    延後匯入的模組有被收進去
  EXE 內建的資源    gui/web、templates 等
  EXE 跑得起來      `update --check` 能執行並回報版本
  版本比線上的新    否則不會有人收到更新
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
    """版本號：以 core/config.py 的 VERSION 為準。

    ⚠ `filevers` / `prodvers` 比對 `X.Y.Z.0`，字串欄位比對 `X.Y.Z`。
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

    # ⚠ dist 裡的 EXE 可能比原始碼舊。
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

    # ⚠ 延後載入的模組（gui/runner.py）要查 EXE 裡的 PYZ，原始碼的 import 掃描看不出來。
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

    # ⚠ 紀錄導去暫存目錄，不混進 dist 的 assistant.log。
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

    # ⚠ 比較版本用更新器自己的 is_newer。
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
