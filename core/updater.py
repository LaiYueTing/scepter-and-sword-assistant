"""檢查 GitHub Release 有沒有新版，下載並就地換掉自己。

⚠ Windows 允許把執行中的 EXE 改名，但不允許覆寫。換檔分兩步：先把自己改名成 `*.exe.old`，
  再把新檔搬到原路徑；下次啟動時由 `cleanup()` 刪除 `.old`。
⚠ 只用標準庫，這支模組在介面啟動時就會匯入。
⚠ 所有失敗都退化成「不更新」，對外的函式回傳 None／False，不往上拋。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import threading
import subprocess
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from core import logger
from core.config import ROOT, VERSION

log = logger.get("update")

REPO = "LaiYueTing/scepter-and-sword-assistant"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
PAGE = f"https://github.com/{REPO}/releases/latest"

# GitHub API 要求帶 User-Agent，否則回 403。
_HEADERS = {
    "User-Agent": f"ScepterSwordAssistant/{VERSION}",
    "Accept": "application/vnd.github+json",
}

CHECK_TIMEOUT = 10.0        # 查版本的逾時（秒）
DOWNLOAD_TIMEOUT = 60.0     # 下載的逾時（秒）

# 同時下載的分段數。
DOWNLOAD_THREADS = 4
# 單一分段失敗時的重試次數，只重抓失敗的那一段。
DOWNLOAD_RETRIES = 3


@dataclass(frozen=True)
class Release:
    """一個版本。`url` 是 EXE 的下載位址。"""

    version: str
    tag: str
    title: str
    notes: str
    url: str
    size: int

    @property
    def size_text(self) -> str:
        return f"{self.size / 1048576:.0f} MB" if self.size else "未知大小"


def _parse(version: str) -> tuple[int, ...]:
    """「v1.0.91.0」→ (1, 0, 91, 0)，無法辨識的段當 0。"""
    nums = re.findall(r"\d+", version or "")
    return tuple(int(n) for n in nums[:4]) or (0,)


def is_newer(candidate: str, current: str = VERSION) -> bool:
    """比較版本，兩邊補到一樣長。"""
    a, b = _parse(candidate), _parse(current)
    width = max(len(a), len(b))
    return a + (0,) * (width - len(a)) > b + (0,) * (width - len(b))


def latest_status() -> tuple["Release | None", str]:
    """查詢 GitHub 最新的 Release，回傳（Release 或 None, 查不到的原因）。

    ⚠ 要分得出「查不到」與「已經是最新」，所以另外回傳原因。
    """
    try:
        req = urllib.request.Request(API, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=CHECK_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as e:
        log.info("查不到更新資訊：%s", e)
        return None, str(e)

    tag = str(data.get("tag_name") or "")
    asset = next((a for a in data.get("assets") or []
                  if str(a.get("name", "")).lower().endswith(".exe")), None)
    if not tag or not asset:
        log.info("最新的 Release 沒有附上 EXE，略過")
        return None, "最新的 Release 沒有附上執行檔"

    return Release(
        version=tag.lstrip("vV"),
        tag=tag,
        title=str(data.get("name") or tag),
        notes=str(data.get("body") or "").strip(),
        url=str(asset.get("browser_download_url") or ""),
        size=int(asset.get("size") or 0),
    ), ""


def latest() -> Release | None:
    """查詢最新的 Release，失敗回傳 None。"""
    return latest_status()[0]


def check_status() -> tuple["Release | None", str]:
    """有更新的版本才回傳 Release；第二個值是查不到的原因（空字串表示查詢成功）。"""
    rel, err = latest_status()
    if err:
        return None, err
    if rel and is_newer(rel.version):
        log.info("有新版本 v%s（目前 v%s）", rel.version, VERSION)
        return rel, ""
    return None, ""


def check() -> Release | None:
    """有更新的版本才回傳，否則 None。"""
    return check_status()[0]

def _target_exe() -> Path:
    """要換掉的檔案，一律以自己的實際路徑（`sys.executable`）為準。

    ⚠ 使用者可以把 EXE 改成任何檔名。開發環境退回 ROOT 底下的預設名字（`can_apply()` 會拒絕換檔）。
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable)
    return ROOT / "杖劍傳說助手.exe"


def _spare_backup(cur: Path) -> Path:
    """挑一個可用的備份路徑，回傳路徑。

    ⚠ `.old` 被佔用或唯讀時 `os.replace` 丟 [WinError 5]。刪不掉就改用帶時間戳的名字。
    """
    first = cur.with_name(cur.name + ".old")
    try:
        first.unlink(missing_ok=True)
        return first
    except OSError:
        log.warning("舊的備份檔還被佔著，改用帶時間戳的名字：%s", first.name)
        return cur.with_name(
            f"{cur.name}.{datetime.now():%Y%m%d%H%M%S}.old")


def can_apply() -> tuple[bool, str]:
    """目前的執行環境能否換檔，回傳（可否, 不行的理由）。"""
    if not getattr(sys, "frozen", False):
        return False, "這是從原始碼執行的版本，請用 git pull 更新"
    if not Path(sys.executable).is_file():
        return False, "找不到自己的執行檔"
    return True, ""


def _probe(url: str) -> tuple[int, bool]:
    """回傳（檔案總長度, 是否支援分段下載），查不到就回傳 (0, False)。

    用 `Range: bytes=0-0` 探測：回 206 代表支援，總長度在 `Content-Range` 的斜線後面。
    """
    try:
        req = urllib.request.Request(
            url, headers={**_HEADERS, "Range": "bytes=0-0"})
        with urllib.request.urlopen(req, timeout=CHECK_TIMEOUT) as resp:
            if resp.status == 206:
                rng = resp.headers.get("Content-Range", "")
                if "/" in rng:
                    return int(rng.rsplit("/", 1)[1]), True
            return int(resp.headers.get("Content-Length") or 0), False
    except (urllib.error.URLError, OSError, ValueError) as e:
        log.debug("探測下載來源失敗：%s", e)
        return 0, False


def _fetch_range(url: str, path: Path, start: int, end: int, bump) -> bool:
    """抓 [start, end] 這一段寫進 `path` 的對應位置。

    ⚠ 每條執行緒開自己的檔案物件：「seek 然後 write」不是原子操作。
    """
    for attempt in range(DOWNLOAD_RETRIES):
        at = start
        try:
            req = urllib.request.Request(
                url, headers={**_HEADERS, "Range": f"bytes={at}-{end}"})
            with urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT) as resp:
                with path.open("r+b") as fh:
                    fh.seek(at)
                    while chunk := resp.read(262144):
                        fh.write(chunk)
                        at += len(chunk)
                        bump(len(chunk))
            if at > end:
                at = end + 1
            if at == end + 1:
                return True
            log.debug("分段 %d-%d 只拿到 %d，重試", start, end, at - start)
        except (urllib.error.URLError, OSError) as e:
            log.debug("分段 %d-%d 失敗（第 %d 次）：%s", start, end, attempt + 1, e)
        # 重試時退回這一段的起點
        bump(start - at)
    return False


def _download_parallel(url: str, path: Path, total: int, on_progress) -> bool:
    """切成幾段同時下載。⚠ 只在對方支援 Range 時使用。"""
    path.unlink(missing_ok=True)
    with path.open("wb") as fh:
        fh.truncate(total)          # 先配置空間，各段直接寫到自己的位置

    lock = threading.Lock()
    done = [0]

    def bump(n: int) -> None:
        with lock:
            done[0] += n
            if on_progress:
                on_progress(done[0], total)

    size = (total + DOWNLOAD_THREADS - 1) // DOWNLOAD_THREADS
    spans = [(i * size, min(total, (i + 1) * size) - 1)
             for i in range(DOWNLOAD_THREADS) if i * size < total]
    with ThreadPoolExecutor(max_workers=len(spans)) as pool:
        results = list(pool.map(
            lambda sp: _fetch_range(url, path, sp[0], sp[1], bump), spans))
    return all(results)


def _download_stream(url: str, path: Path, total: int, on_progress) -> bool:
    """單一連線下載，對方不支援 Range 時使用。"""
    try:
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT) as resp:
            got = 0
            with path.open("wb") as fh:
                while chunk := resp.read(262144):
                    fh.write(chunk)
                    got += len(chunk)
                    if on_progress:
                        on_progress(got, total)
    except (urllib.error.URLError, OSError) as e:
        log.warning("下載更新失敗：%s", e)
        return False
    return True


def download(rel: Release, on_progress=None) -> Path | None:
    """下載到 EXE 旁邊的暫存檔。`on_progress(已下載, 總計)` 可省略。

    對方支援 Range 就分段下載（失敗只重抓那一段），否則用單一連線。

    ⚠ 要驗大小：連線半途中斷時 `read()` 回傳空字串，迴圈會正常結束。截斷的 EXE 無法啟動。
    ⚠ 要驗檔頭：GitHub 偶爾回一頁 HTML（維護中、速率限制）。
    """
    # ⚠ 暫存檔名跟著自己的實際檔名走，並帶 `.new` 副檔名。
    cur = _target_exe()
    target = cur.with_name(cur.name + ".new")
    part = cur.with_name(cur.name + ".part")

    total, ranged = _probe(rel.url)
    if not total:
        total = rel.size
    try:
        if ranged and total > 4 * 1024 * 1024 and DOWNLOAD_THREADS > 1:
            log.info("分成 %d 段下載（共 %.0f MB）",
                     DOWNLOAD_THREADS, total / 1048576)
            ok = _download_parallel(rel.url, part, total, on_progress)
        else:
            ok = _download_stream(rel.url, part, total, on_progress)
    except OSError as e:
        log.warning("下載更新失敗：%s", e)
        ok = False

    if not ok:
        part.unlink(missing_ok=True)
        return None

    got = part.stat().st_size
    if total and got != total:
        log.warning("下載不完整：只拿到 %.1f / %.1f MB",
                    got / 1048576, total / 1048576)
        part.unlink(missing_ok=True)
        return None
    if part.read_bytes()[:2] != b"MZ":
        log.warning("下載到的不是執行檔（可能是 GitHub 回的錯誤頁）")
        part.unlink(missing_ok=True)
        return None

    os.replace(part, target)
    # 訊息用 MB 表示。
    log.info("已下載 %s（%.0f MB）", target.name, got / 1048576)
    return target


def apply(new_exe: Path) -> tuple[bool, str]:
    """把新檔換到自己的位置，回傳（成功與否, 失敗說明）。⚠ 第二步失敗要把舊檔搬回來。"""
    ok, why = can_apply()
    if not ok:
        return False, why

    cur = _target_exe()
    backup = _spare_backup(cur)

    try:
        os.replace(cur, backup)          # 執行中的 EXE 可以改名，不能覆寫
    except OSError as e:
        # ⚠ 訊息要寫出下一步：最常見的成因是另一個助手還開著，其次是防毒的即時掃描。
        return False, "\n".join([
            f"換不掉舊版：{e}",
            "請確認沒有另一個助手還在執行（縮到系統匣的也算），"
            "或暫時關掉防毒的即時掃描再試一次。",
            f"新版已經下載好，也可以關掉助手之後手動把 {new_exe.name} "
            f"改名成 {cur.name} 換上去。",
        ])

    try:
        os.replace(new_exe, cur)
    except OSError as e:
        os.replace(backup, cur)          # 搬回來，維持可執行
        return False, f"新版搬不進去：{e}"

    log.info("已更新到 %s，重新啟動後生效", new_exe.name)
    return True, ""


def cleanup() -> None:
    """刪除上次更新留下的檔案，啟動時呼叫。

    三種都要清：`.old`、`*.<時間戳>.old`（`.old` 被佔用時的備用名）、`.new` / `.part`。
    """
    leftovers = (list(ROOT.glob("*.exe.old")) + list(ROOT.glob("*.exe.*.old"))
                 + list(ROOT.glob("*.new")) + list(ROOT.glob("*.part")))
    for leftover in leftovers:
        try:
            leftover.unlink()
        except OSError:
            pass                          # 還被佔用就下次再清


def sweep_temp() -> int:
    """清掉自己留在 %TEMP% 的 `_MEI` 暫存目錄（行程被強制結束時留下的），回傳清掉幾個。

    ⚠ 只清裡面有 `config.example.yaml` 的目錄，別的 PyInstaller 程式也叫 `_MEI*`。
    ⚠ 刪除前先試刪 `python3XX.dll`：活著的行程必定鎖著它，刪得掉才代表沒有人在用。
      不可用開啟檔案探測（預設共用模式允許再開一次），也不可挑其他 DLL（要用到才載入）。
    """
    if not getattr(sys, "frozen", False):
        return 0

    keep = Path(getattr(sys, "_MEIPASS", "") or "x").resolve()
    swept = 0
    try:
        candidates = list(Path(tempfile.gettempdir()).glob("_MEI*"))
    except OSError:
        return 0

    for folder in candidates:
        try:
            if not folder.is_dir() or folder.resolve() == keep:
                continue
            if not (folder / "config.example.yaml").is_file():
                continue                  # 別的程式的目錄
            probe = next(folder.glob("python3[0-9]*.dll"), None)
            if probe is not None:
                probe.unlink()             # 刪得掉代表沒有行程在用
            shutil.rmtree(folder)
            swept += 1
        except OSError:
            continue                       # 鎖著或刪不掉就跳過

    if swept:
        log.info("清掉 %d 份上次沒收拾乾淨的暫存資料", swept)
    return swept


def _clean_env() -> dict[str, str]:
    """複製一份環境變數，移除 PyInstaller 的私有變數。

    ⚠ 啟動自己的 EXE 之前一定要清：bootloader 靠 `_PYI_PARENT_PROCESS_LEVEL` 與
      `_PYI_APPLICATION_HOME_DIR` 判定已解壓，會跳過解壓而載入舊行程已刪除的目錄。
      `_MEIPASS2` 是 PyInstaller 5 以前的名字。
    """
    return {k: v for k, v in os.environ.items()
            if not k.startswith("_PYI_") and k != "_MEIPASS2"}


def restart() -> bool:
    """排定一個背景 PowerShell，等這個行程結束後啟動新版。

    ⚠ 不可直接 Popen 新版：防多開的 mutex 要等這個行程結束才釋放。
    ⚠ 旗標只能給 `CREATE_NO_WINDOW`：`DETACHED_PROCESS` 會讓 PowerShell 當場結束（tests/test_updater.py）。
    ⚠ 環境變數要走 `_clean_env()`。
    ⚠ 啟動前先等舊版的暫存目錄消失（最多 20 秒）：清理是父行程做的，只等子行程結束不夠。
    """
    exe = Path(sys.executable)
    mei = getattr(sys, "_MEIPASS", "")
    wait_mei = (
        f"$mei = '{mei}'; "
        f"for ($i = 0; $i -lt 100 -and (Test-Path -LiteralPath $mei); $i++) "
        f"{{ Start-Sleep -Milliseconds 200 }}; "
    ) if mei else ""
    script = (f"Wait-Process -Id {os.getpid()} -ErrorAction SilentlyContinue; "
              + wait_mei
              + f"Start-Sleep -Milliseconds 1500; "
              f"Start-Process -FilePath '{exe}'")
    try:
        subprocess.Popen(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden",
             "-Command", script],
            env=_clean_env(),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError as e:
        log.warning("排不了重新啟動：%s", e)
        return False
    return True
