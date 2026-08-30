"""檢查 GitHub Release 有沒有新版，下載並就地換掉自己。

發布的是**單一 EXE**，所以更新就是「把新的那個檔案換上去」——不需要安裝程式，
也不需要另外一支更新器行程。

⚠ **Windows 允許把執行中的 EXE 改名，但不允許覆寫它。** 換檔因此是兩步：
  先把自己改名成 `*.exe.old`（那個 handle 仍然有效，程式照常跑），再把新檔
  搬到原本的路徑。下次啟動時 `cleanup()` 把 `.old` 刪掉。
  這條路不必等自己結束，也就不需要一支「等父行程退出再動手」的批次檔。

⚠ **只用標準庫。** 這支模組會在 GUI 啟動時被匯入，多拉一個第三方套件進來就是
  多幾百毫秒的啟動時間，而它做的事只有一個 HTTPS GET。

⚠ **每一種失敗都要能安靜退化成「不更新」。** 沒有網路、GitHub 掛掉、Release
  還沒發、防毒擋下下載——這些都不該讓助手不能用，所以對外的函式一律回傳
  None／False 而不是往上拋。
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

# GitHub 的 API 一律要求帶 User-Agent，沒帶會直接回 403。
_HEADERS = {
    "User-Agent": f"ScepterSwordAssistant/{VERSION}",
    "Accept": "application/vnd.github+json",
}

CHECK_TIMEOUT = 10.0        # 查版本：使用者在等，逾時就當成沒有更新
DOWNLOAD_TIMEOUT = 60.0     # 下載：EXE 有一百多 MB，慢的網路要留餘裕

# 分成幾段同時抓。4 是實測與保守之間的取捨——再多對 CDN 幫助有限，
# 而且連線數愈多，防毒的連線監控愈可能介入。
DOWNLOAD_THREADS = 4
# 單一分段失敗時重抓幾次。網路不穩的使用者正是這個功能要救的人。
DOWNLOAD_RETRIES = 3


@dataclass(frozen=True)
class Release:
    """一個版本。`url` 是那顆 EXE 的下載位址，沒有 EXE 的 Release 不會被建立。"""

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
    """「v1.0.91.0」→ (1, 0, 91, 0)。認不出來的段一律當 0，不要拋。"""
    nums = re.findall(r"\d+", version or "")
    return tuple(int(n) for n in nums[:4]) or (0,)


def is_newer(candidate: str, current: str = VERSION) -> bool:
    """比大小時把兩邊補到一樣長，免得 1.0.92 被判成小於 1.0.92.0。"""
    a, b = _parse(candidate), _parse(current)
    width = max(len(a), len(b))
    return a + (0,) * (width - len(a)) > b + (0,) * (width - len(b))


def latest_status() -> tuple["Release | None", str]:
    """問 GitHub 最新的 Release。回傳（Release 或 None, 查不到的原因）。

    ⚠ **「查不到」和「已經是最新」不是同一件事。** `latest()` 把兩種都變成 None，
      而介面要據此決定說哪一句話——沒網路的時候跳「已經是最新版本」就是在說謊，
      而使用者正是靠那句話決定要不要繼續用舊版跑整晚。
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
    """問 GitHub 最新的 Release 是哪一個。任何失敗都回 None。"""
    return latest_status()[0]


def check_status() -> tuple["Release | None", str]:
    """有比現在新的版本才回傳 Release；第二個值是查不到的原因（空字串＝問到了）。"""
    rel, err = latest_status()
    if err:
        return None, err
    if rel and is_newer(rel.version):
        log.info("有新版本 v%s（目前 v%s）", rel.version, VERSION)
        return rel, ""
    return None, ""


def check() -> Release | None:
    """有比現在新的版本才回傳，否則 None。"""
    return check_status()[0]

def _target_exe() -> Path:
    """更新要換掉的那一個檔案。

    ⚠ 一律以**自己的實際路徑**為準，不要用寫死的名字。使用者可以把 EXE 改成
      任何檔名（GitHub 的附件叫 ScepterSwordAssistant.exe，而桌面捷徑指向的
      是他自己命名的那一個），寫死就會換錯檔案、或在旁邊多生一個。

    沒有 frozen 時退回 ROOT 底下的預設名字——那只有開發環境會走到，而那條路
    `can_apply()` 本來就會拒絕換檔。
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable)
    return ROOT / "杖劍傳說助手.exe"


def _spare_backup(cur: Path) -> Path:
    """挑一個搬得動的備份路徑，回傳要用的那個。

    ⚠ 舊的 `.old` 常常還被佔著：上一版的行程沒真的關掉（縮在系統匣就是這樣，
      使用者看到的是「處理程序有兩個」）、防毒正在掃、或者檔案是唯讀的。而
      `os.replace` 的**目標**被佔用時丟的是 **[WinError 5] 存取被拒**——訊息
      指著新舊兩個路徑，完全看不出真正卡住的是那個 `.old`。

    實測兩種情況都會踩到（被別的行程開著、唯讀屬性），所以刪不掉就換一個帶
    時間戳的名字，不要在同一個路徑上硬碰硬。
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
    """現在這個執行環境換不換得了檔。回傳（可以嗎, 不行的理由）。"""
    if not getattr(sys, "frozen", False):
        return False, "這是從原始碼執行的版本，請用 git pull 更新"
    if not Path(sys.executable).is_file():
        return False, "找不到自己的執行檔"
    return True, ""


def _probe(url: str) -> tuple[int, bool]:
    """回傳（檔案總長度, 支不支援分段下載）。問不到就 (0, False)。

    用 `Range: bytes=0-0` 探：回 206 就代表支援，總長度在 `Content-Range` 的
    斜線後面。這比 HEAD 可靠——有些 CDN 對 HEAD 的回應和實際下載不一致。
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

    ⚠ 每條執行緒開**自己的**檔案物件再 seek，不共用。共用一個檔案物件的話
      「seek 然後 write」不是原子的，兩條同時寫就會互相蓋到對方的位置。
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
        # 重試時已經寫下去的部分不算數，退回這一段的起點重抓
        bump(start - at)
    return False


def _download_parallel(url: str, path: Path, total: int, on_progress) -> bool:
    """切成幾段同時抓。⚠ 只在對方支援 Range 時才走這條。"""
    path.unlink(missing_ok=True)
    with path.open("wb") as fh:
        fh.truncate(total)          # 先把空間開好，各段直接寫到自己的位置

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
    """一條連線從頭抓到尾。對方不支援 Range 時的退路。"""
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

    對方支援 Range 就切成幾段同時抓——單一連線被限速時差很多，而且**某一段失敗
    只要重抓那一段**，不必整個一百多 MB 重來。不支援就退回單條連線。

    ⚠ **一定要驗大小。** `resp.read()` 在連線半途斷掉時回傳空字串，`while` 迴圈
      就這樣**正常結束**——沒有例外、沒有錯誤。少了這道檢查，一個截斷的檔案會
      被當成下載完成、改名、然後換上去，使用者拿到的是**每次啟動都失敗**的執行檔：

          Failed to load Python DLL '...python314.dll'.
          LoadLibrary: 找不到指定的模組。

      （單檔打包的 EXE 是個壓縮包，截斷之後 bootloader 解壓不出裡面的 DLL。）
      實測 2026-08-25 有使用者卡在 103 MB 下載到 100 MB 的地方，就是這樣。

    ⚠ 也要看檔頭。GitHub 偶爾會回一頁 HTML（維護中、速率限制），那種內容大小
      對得上與否都不該拿去換執行檔。
    """
    # ⚠ 暫存檔名要**跟著自己的檔名走**，而且一看就知道是暫存的。
    #   原本寫死成「杖劍傳說助手-v1.0.1.exe」，兩個後果：使用者的 EXE 其實叫
    #   ScepterSwordAssistant.exe（GitHub 附件名），於是旁邊多出一個看起來
    #   像正式版的檔案；而換檔失敗時它就留在那裡，讓人以為「捷徑要改指到這個」。
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
    # ⚠ 用 MB 不用位元組。「81208677 位元組」讀的人得自己心算才知道是不是
    #   完整的一份，而這一行的用途正是「確認拿到的份量對不對」。
    log.info("已下載 %s（%.0f MB）", target.name, got / 1048576)
    return target


def apply(new_exe: Path) -> tuple[bool, str]:
    """把新檔換到自己的位置。回傳（成功嗎, 失敗的說明）。

    ⚠ 第二步失敗要把舊的搬回來。少了這段就會變成「更新沒成功，而且原本的
      程式也不見了」——那比更新失敗嚴重得多。
    """
    ok, why = can_apply()
    if not ok:
        return False, why

    cur = _target_exe()
    backup = _spare_backup(cur)

    try:
        os.replace(cur, backup)          # 執行中的 EXE 改得了名，覆寫不了
    except OSError as e:
        # ⚠ 訊息要說得出**下一步做什麼**。原本只寫「換不掉舊版：[WinError 5]
        #   存取被拒」，而使用者從那句話完全看不出要去關掉什麼——實際上最常見
        #   的成因是另一個助手還開著（縮在系統匣也算，工作管理員裡會看到兩個
        #   處理程序），其次是防毒的即時掃描正握著檔案。
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
        os.replace(backup, cur)          # 搬回來，維持在可以執行的狀態
        return False, f"新版搬不進去：{e}"

    log.info("已更新到 %s，重新啟動後生效", new_exe.name)
    return True, ""


def cleanup() -> None:
    """刪掉上一次更新留下的殘骸。啟動時呼叫。

    ⚠ 三種都要收：`.old`（換檔成功後的舊版）、`*.<時間戳>.old`（`.old` 當時
      被佔著而改用的備用名）、`.new` / `.part`（下載到一半或換檔失敗留下的）。
      少收哪一種，那個檔案就會一直躺在 EXE 旁邊讓使用者猜它是什麼。
    """
    leftovers = (list(ROOT.glob("*.exe.old")) + list(ROOT.glob("*.exe.*.old"))
                 + list(ROOT.glob("*.new")) + list(ROOT.glob("*.part")))
    for leftover in leftovers:
        try:
            leftover.unlink()
        except OSError:
            pass                          # 還被佔著就下次再說，不值得吵使用者


def sweep_temp() -> int:
    """清掉自己留在 %TEMP% 的 `_MEI` 殘骸，回傳清掉幾個。

    單檔打包的程式每次執行都會把自己解壓到 `%TEMP%\\_MEI******`，正常結束時
    bootloader 會刪掉。但**行程被強制結束就不會**（工作管理員、Stop-Process、
    當機），而那一份有一百多 MB——實測開發機上累積了 **33 個、8.3 GB**。
    使用者也會看到 bootloader 自己的警告：

        Failed to remove temporary directory: ...\\_MEI576122

    ⚠ **只清「確定是我們的」那些。** `%TEMP%` 底下別的 PyInstaller 程式也叫
      `_MEI*`，判準是裡面有沒有 `config.example.yaml`（那是我們打包進去的）。

    ⚠ **刪之前要先確認沒有人在用，不能直接 `rmtree(ignore_errors=True)`。**
      唯讀工具（doctor、selftest）不上防多開的鎖，可能正有一份在跑；忽略錯誤地
      刪下去會把它**刪成半殘**而當場炸掉。

    ⚠ **探測方式是「試著刪掉一個 DLL」，不是「試著開啟」。** 開啟沒有用——
      Windows 的預設共用模式允許再開一次，實測 `open("ab")` 對正被使用的檔案
      **會成功**，於是 `rmtree` 照樣開刪，把目錄刪成半殘才卡住。而刪除不一樣：
      預設的開檔沒有 `FILE_SHARE_DELETE`，映射中的 DLL 更是刪不掉——刪得掉就
      代表沒有人在用。失敗的話整個目錄跳過，什麼都沒動到。
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
                continue                  # 別人的程式，不要碰
            probe = next(folder.glob("*.dll"), None)
            if probe is not None:
                probe.unlink()             # 刪得掉就代表沒有行程在用
            shutil.rmtree(folder)
            swept += 1
        except OSError:
            continue                       # 鎖著或刪不掉就跳過，下次再說

    if swept:
        log.info("清掉 %d 份上次沒收拾乾淨的暫存資料", swept)
    return swept


def _clean_env() -> dict[str, str]:
    """複製一份環境變數，把 PyInstaller 的私有那幾個拿掉。

    ⚠ **啟動自己的 EXE 之前一定要清，否則新版根本不會解壓。** 單檔打包的
      bootloader 靠 `_PYI_PARENT_PROCESS_LEVEL` 與 `_PYI_APPLICATION_HOME_DIR`
      認出「我是已經解壓好的子行程」，於是**整段解壓被跳過**，直接去載入那個
      目錄裡的 DLL。而這些變數會被子行程開的每一個行程繼承下去——PowerShell
      接到，`Start-Process` 再原封不動傳給新版 EXE，新版就對著**舊行程早已刪掉
      的**目錄找 DLL：

          Failed to load Python DLL '...\\_MEI155122\\python314.dll'.
          LoadLibrary: 找不到指定的模組。

      A／B 實測：同一顆 EXE，帶著這些變數啟動必定卡在這個對話框，清乾淨則正常。
      雙擊不會有事（Explorer 沒有這些變數），所以只有更新後的重新啟動會炸。

    ⚠ `_MEIPASS2` 是 PyInstaller 5 以前的名字，一併清掉——換版本時不必回頭想。
    """
    return {k: v for k, v in os.environ.items()
            if not k.startswith("_PYI_") and k != "_MEIPASS2"}


def restart() -> bool:
    """關掉自己並開起新版。

    ⚠ 不能直接 `Popen` 新的 EXE 就走人：防多開的 mutex 要等這個行程結束才會
      釋放，新的那個會以為「已經有一份在跑」而立刻退出。所以委託一個背景的
      PowerShell 等我們結束再啟動。

    ⚠ **旗標只能給 `CREATE_NO_WINDOW`。** 量出來的：`DETACHED_PROCESS`（單獨給
      或跟 CREATE_NO_WINDOW 一起給）會讓那個 PowerShell 當場死掉——`Popen` 本身
      不報錯、PID 也拿得到，但它什麼都沒做完，症狀是「更新完就再也開不起來」。
      三種組合的實測見 tests/test_updater.py。

    ⚠ **環境變數一定要走 `_clean_env()`。** 少了它，新版會跳過解壓去載入舊版
      那個已經被刪掉的目錄，開不起來——理由見 `_clean_env` 的說明。

    ⚠ 啟動前先等舊版的暫存目錄消失（最多 20 秒），免得兩份一百多 MB 同時佔著
      `%TEMP%`，也讓舊版的清理跑完再說。
      ⚠ `Wait-Process` 等的是**跑 Python 的那個子行程**，而清理是**父行程**做的
        ——所以光等行程結束不夠，一定要等目錄。
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
