"""ADB 連線層：負責與 Android 模擬器溝通，提供截圖與輸入操作。

所有操作都透過 ADB 完成，屬於「後台操作」——不會搶佔實體滑鼠鍵盤，
也不需要模擬器視窗保持在前景，甚至可以最小化。
"""

from __future__ import annotations

import random
import shutil
import re
import subprocess
import time
from pathlib import Path

import cv2
import numpy as np

from . import logger
from .config import BUNDLE, ROOT, Config

log = logger.get("adb")

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

# 套件名對應到遊戲的顯示名稱。紀錄裡只寫 com.m88.idleXX 看不出那是什麼，
# 寫成「杖劍傳說（com.m88.idleXX）」兩邊都留著。認不出來的套件就只寫套件名。
_APP_NAMES = {"com.m88.idleXX": "杖劍傳說"}


def app_label(package: str) -> str:
    """套件名加上遊戲名稱，給紀錄用。"""
    name = _APP_NAMES.get(package)
    return f"{name}（{package}）" if name else package


class AdbError(RuntimeError):
    """ADB 指令執行失敗。"""


def _install_adb() -> Path | None:
    """把打包在 EXE 裡的 adb 複製到 EXE 旁邊，回傳新位置。

    ⚠ **不能直接執行 `sys._MEIPASS` 裡的 adb.exe。** adb 會 fork 一個常駐的
      daemon，而它會一直持有自己的執行檔目錄——也就是每次執行都不同的
      `_MEI******` 暫存資料夾。後果有兩個：

        1. 程式結束時 PyInstaller 刪不掉那個資料夾（檔案被佔用），暫存區愈積愈多
        2. 下次啟動解壓到**新的** `_MEI`，新的客戶端連上 5037 埠接到的卻是那個
           「執行檔目錄已經殘缺」的舊 daemon，`adb connect` 於是卡到逾時，而
           錯誤訊息只寫「connect timed out」，看不出真正的原因

    複製到 EXE 旁邊之後路徑就固定了，daemon 也不再跟暫存目錄綁在一起。
    複製失敗（例如放在唯讀的位置）就回 None，改用內建的那份。
    """
    src = BUNDLE / "platform-tools"
    dst = ROOT / "platform-tools"
    if not (src / "adb.exe").is_file() or src == dst:
        return None
    try:
        dst.mkdir(parents=True, exist_ok=True)
        for item in src.iterdir():
            if item.is_file() and not (dst / item.name).exists():
                shutil.copy2(item, dst / item.name)
        log.info("已將 adb 安裝到 %s（避免 daemon 綁在暫存目錄上）", dst)
        return dst / "adb.exe"
    except OSError as e:
        log.warning("adb 無法複製到程式目錄（%s），改用內建的那份", e)
        return None


def resolve_adb(path_hint: str) -> str:
    """找出可用的 adb 執行檔。

    順序：設定檔指定的路徑 → EXE 旁邊的 platform-tools → 複製一份出來用
    → 打包進 EXE 的那份 → 系統 PATH。
    """
    candidates: list[Path | str] = []
    if path_hint and path_hint != "adb":
        candidates.append(Path(path_hint))

    external = ROOT / "platform-tools" / "adb.exe"
    if external.is_file():
        candidates.append(external)
    else:
        installed = _install_adb()
        if installed:
            candidates.append(installed)
    candidates.append(BUNDLE / "platform-tools" / "adb.exe")

    for c in candidates:
        p = Path(c)
        if p.is_file():
            return str(p)

    found = shutil.which(path_hint or "adb")
    if found:
        return found

    raise AdbError(
        "找不到 adb 執行檔。請在 config.yaml 的 adb.path 指定絕對路徑，"
        "或把 platform-tools 放到專案目錄下。"
    )


class Device:
    """代表一台已連線的模擬器。"""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.adb = resolve_adb(cfg.adb.path)
        self.timeout = cfg.adb.timeout
        self.width = cfg.device.width
        self.height = cfg.device.height
        self.serial = cfg.device.target      # 可能是 auto，connect 時才定案
        self._spec_logged = False            # 裝置規格只報告一次，見 _verify_spec

    # ---------- 底層指令 ----------

    def _run(self, args: list[str], timeout: int | None = None) -> subprocess.CompletedProcess:
        cmd = [self.adb, *args]
        return subprocess.run(
            cmd,
            capture_output=True,
            timeout=timeout or self.timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            # ⚠ 明確指定工作目錄為 adb 自己的資料夾。不指定的話子行程會繼承
            #   我們的 cwd，而 adb 那個常駐 daemon 會一直佔著它——打包執行時
            #   那可能就是 PyInstaller 的暫存目錄，於是又刪不掉了。
            cwd=str(Path(self.adb).parent),
        )

    def _run_device(self, args: list[str], timeout: int | None = None) -> subprocess.CompletedProcess:
        return self._run(["-s", self.serial, *args], timeout=timeout)

    def shell(self, command: str, timeout: int | None = None) -> str:
        proc = self._run_device(["shell", command], timeout=timeout)
        if proc.returncode != 0:
            raise AdbError(f"shell 失敗：{command}\n{proc.stderr.decode('utf-8', 'ignore')}")
        return proc.stdout.decode("utf-8", "ignore").strip()

    # ---------- 連線 ----------

    def list_devices(self) -> list[tuple[str, str]]:
        """列出 adb 看得到的裝置，回傳 [(序號, 狀態)]。"""
        proc = self._run(["devices"], timeout=self.timeout)
        found = []
        for line in proc.stdout.decode("utf-8", "ignore").splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2:
                found.append((parts[0], parts[1]))
        return found

    def model_of(self, serial: str) -> str:
        proc = self._run(["-s", serial, "shell", "getprop", "ro.product.model"])
        return proc.stdout.decode("utf-8", "ignore").strip()

    def _ensure_server(self) -> None:
        """先把 adb server（daemon）叫起來，再做真正的連線。

        ⚠ 少了這一步會在冷啟動時連不上。`adb connect` 發現 server 沒在跑時會自己
          啟動一個，但**那段時間算在 connect 的 timeout 裡**，而 server 冷啟動
          可能要十幾秒（防毒會對剛解壓出來的執行檔做一次完整掃描）。兩件事擠在
          20 秒裡就會逾時，而訊息只說「connect 逾時」，看不出卡在哪。
          相較之下 server 已經在跑時，同一個 connect 只要 0.15 秒。

        起不來也不拋錯——後面的 `is_online()` 會給出完整的排查步驟。
        """
        try:
            self._run(["start-server"], timeout=max(self.timeout, 60))
        except subprocess.TimeoutExpired:
            log.warning("adb server 啟動逾時，仍會試著連線")

    def connect(self) -> None:
        """建立連線並驗證裝置規格。

        ⚠ `serial: auto` 只是「從已經連上的裝置裡挑一台」，它本身不會建立連線。
          跨機器連線時 adb server 一重啟（或電腦重開）就什麼都不剩，排程那一輪
          會直接失敗在「找不到任何已連線的裝置」。所以只要設定檔填了 host/port，
          即使 serial 是 auto 也先 `adb connect` 一次——這樣才自己接得回來。
        """
        self._ensure_server()
        self._try_connect()

        if not self.is_online():
            # 連不上有一種很難查的原因：5037 埠上掛著一個狀態壞掉的舊 daemon
            # （例如它的執行檔目錄已經被刪，見 _install_adb）。這種情況下
            # 重啟 server 就會好，所以自己先試一次再放棄。
            log.warning("連線失敗，重啟 adb server 後再試一次")
            try:
                self._run(["kill-server"], timeout=self.timeout)
            except subprocess.TimeoutExpired:
                pass
            self._ensure_server()
            self._try_connect()

        if not self.is_online():
            raise AdbError(
                f"無法連線到 {self.serial}。請確認：\n"
                "  1. 模擬器已啟動\n"
                "  2. 模擬器允許遠端 ADB 連線\n"
                "     （在模擬器的設定裡找 ADB／連線那一類選項；\n"
                "      僅同一台電腦執行時可略過這步）\n"
                "  3. 連接埠與模擬器顯示的 ADB 埠一致\n"
                "     （查不到埠號時，介面上的「探索」會自己找）\n"
                "  4. 若跨機器連線，防火牆需放行該連接埠\n"
                "  5. 對方電腦的防毒／網路防護有沒有把這台機器暫時封鎖\n"
                "     （ESET、卡巴這類會擋「連接埠掃描」，被擋住時那台機器的\n"
                "      所有連接埠都會靜靜逾時，看起來就像模擬器沒開）\n"
                "  用 `python main.py devices` 可以列出目前看得到的裝置"
            )
        self._verify_spec()

    def _try_connect(self) -> None:
        """依設定建立連線。auto 也要先 connect——見 connect() 的說明。"""
        if self.serial == "auto":
            if self.cfg.device.port:
                self._network_connect(f"{self.cfg.device.host}:{self.cfg.device.port}")
            self._resolve_auto()
        elif self.cfg.device.is_network:
            self._network_connect(self.serial)

    def _network_connect(self, target: str) -> None:
        """對網路位址執行 adb connect，把結果講成中文。連不上不拋錯——
        呼叫端接著會用 is_online() 判斷，那裡的錯誤訊息完整得多。

        ⚠ 逾時也不要讓 `subprocess.TimeoutExpired` 往上冒。那個例外的訊息是一長
          串英文命令列（`Command '[...adb.exe, connect, ...]' timed out`），
          使用者只看得到「有東西壞了」，看不出要去檢查模擬器還是網路。
        """
        try:
            proc = self._run(["connect", target], timeout=self.timeout)
        except subprocess.TimeoutExpired:
            log.warning("連線 %s 逾時（%d 秒）", target, self.timeout)
            return
        out = proc.stdout.decode("utf-8", "ignore").strip()
        # adb 的原始輸出是英文，正常情況講中文結論就好，異常時才需要看原文
        detail = out or proc.stderr.decode("utf-8", "ignore").strip()
        if "already connected" in detail:
            log.info("已連線到 %s", target)
        elif detail.startswith("connected to"):
            log.info("連線成功：%s", target)
        else:
            log.info("連線 %s：%s", target, detail)

    def _resolve_auto(self) -> None:
        """serial 設成 auto 時，挑第一台連線中的裝置。"""
        online = [s for s, state in self.list_devices() if state == "device"]
        if not online:
            raise AdbError(
                "找不到任何已連線的裝置。請先啟動模擬器，"
                "或在 config.yaml 指定 host/port。"
            )
        self.serial = online[0]
        if len(online) > 1:
            log.warning("偵測到 %d 台裝置，自動選用 %s：%s",
                        len(online), self.serial, "、".join(online))
        else:
            log.info("自動選用裝置：%s", self.serial)

    def is_online(self) -> bool:
        return any(s == self.serial and state == "device"
                   for s, state in self.list_devices())

    def _verify_spec(self) -> None:
        """檢查解析度與 DPI 是否符合設定，不符只警告不中斷。

        每輪排程醒來都會重新連線，所以規格正常時只在第一次寫紀錄——否則跑一整天
        會累積幾十行一樣的「裝置規格」。不符合仍然每次都警告（那是要看到的）。
        """
        size = self.shell("wm size")
        density = self.shell("wm density")
        # 原始輸出長這樣：「Physical size: 720x1280」、「Physical density: 320」
        m = re.search(r"(\d+)x(\d+)", size)
        d = re.search(r"(\d+)", density)
        if not self._spec_logged:
            self._spec_logged = True
            log.info("裝置規格：%s、%s dpi",
                     f"{m.group(1)}x{m.group(2)}" if m else size.strip(),
                     d.group(1) if d else density.strip())

        expect = f"{self.width}x{self.height}"
        if expect not in size:
            log.warning(
                "解析度與設定不符（預期 %s）。模板座標會偏移，"
                "請把模擬器調成 %s 或重新製作模板。", expect, expect,
            )
        if str(self.cfg.device.dpi) not in density:
            log.warning("DPI 與設定不符（預期 %s）。", self.cfg.device.dpi)

    # ---------- 截圖 ----------

    def screencap(self) -> np.ndarray:
        """抓取一張畫面，回傳 OpenCV BGR 影像。

        用 `exec-out` 直接取得 binary stdout，避開 shell 重導向會插入 BOM、
        把 \\n 換成 \\r\\n 而破壞 PNG 的問題。
        """
        proc = self._run_device(["exec-out", "screencap", "-p"])
        raw = proc.stdout
        if not raw:
            raise AdbError(f"截圖失敗：{proc.stderr.decode('utf-8', 'ignore')}")

        if not raw.startswith(PNG_MAGIC):
            # 舊版 adb 或某些模擬器仍會做換行轉換，這裡補救一次
            raw = raw.replace(b"\r\n", b"\n")
        if not raw.startswith(PNG_MAGIC):
            raise AdbError("截圖資料不是有效的 PNG，請確認 adb 版本")

        img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise AdbError("PNG 解碼失敗")
        return img

    def save_screencap(self, path: Path | str) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        img = self.screencap()
        # 用 imencode 寫檔，避免 cv2.imwrite 對非 ASCII 路徑失敗
        ok, buf = cv2.imencode(".png", img)
        if not ok:
            raise AdbError("PNG 編碼失敗")
        path.write_bytes(buf.tobytes())
        return path

    # ---------- 輸入 ----------

    def tap(self, x: int, y: int, jitter: int | None = None) -> None:
        """點擊座標，預設帶隨機抖動。"""
        j = self.cfg.runtime.tap_jitter if jitter is None else jitter
        if j > 0:
            x += random.randint(-j, j)
            y += random.randint(-j, j)
        x = max(0, min(self.width - 1, x))
        y = max(0, min(self.height - 1, y))
        self.shell(f"input tap {x} {y}")
        log.debug("tap (%d, %d)", x, y)
        time.sleep(self.cfg.runtime.post_tap_delay)

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        self.shell(f"input swipe {x1} {y1} {x2} {y2} {duration_ms}")
        log.debug("swipe (%d,%d) → (%d,%d) %dms", x1, y1, x2, y2, duration_ms)
        time.sleep(self.cfg.runtime.post_tap_delay)

    def key(self, keycode: str | int) -> None:
        self.shell(f"input keyevent {keycode}")
        time.sleep(self.cfg.runtime.post_tap_delay)

    def back(self) -> None:
        self.key("KEYCODE_BACK")

    # ---------- 應用程式 ----------

    def launch_app(self, package: str) -> None:
        self.shell(f"monkey -p {package} -c android.intent.category.LAUNCHER 1")
        log.info("啟動應用程式：%s", app_label(package))

    def stop_app(self, package: str) -> None:
        self.shell(f"am force-stop {package}")
        log.info("關閉應用程式：%s", app_label(package))

    def is_app_running(self, package: str) -> bool:
        # pidof 印的是 PID 數字，不是套件名，所以要看有沒有輸出而非比對名稱
        out = self.shell(f"pidof {package} || true").strip()
        return any(token.isdigit() for token in out.split())
