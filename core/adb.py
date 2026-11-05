"""ADB 連線層：與 Android 模擬器溝通，提供截圖與輸入操作。不佔用實體滑鼠鍵盤，模擬器可以最小化。"""

from __future__ import annotations

import random
import shutil
import re
import struct
import subprocess
import time
from pathlib import Path

import cv2
import numpy as np

from . import logger
from .config import BUNDLE, ROOT, Config

log = logger.get("adb")

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

# 套件名對應的遊戲名稱，寫紀錄用。
_APP_NAMES = {"com.m88.idleXX": "杖劍傳說"}


def app_label(package: str) -> str:
    """套件名加上遊戲名稱，給紀錄用。"""
    name = _APP_NAMES.get(package)
    return f"{name}（{package}）" if name else package


class AdbError(RuntimeError):
    """ADB 指令執行失敗。"""


def _install_adb() -> Path | None:
    """把打包在 EXE 裡的 adb 複製到 EXE 旁邊，回傳新位置；複製失敗回傳 None。

    ⚠ 不可直接執行 `sys._MEIPASS` 裡的 adb.exe：常駐的 daemon 會佔住暫存目錄，
      造成目錄刪不掉，下次啟動的 `adb connect` 也會逾時。
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
        self._raw_capture = True             # 原始格式截圖可用；解析失敗一次就改用 PNG

    # ---------- 底層指令 ----------

    def _run(self, args: list[str], timeout: int | None = None) -> subprocess.CompletedProcess:
        cmd = [self.adb, *args]
        return subprocess.run(
            cmd,
            capture_output=True,
            timeout=timeout or self.timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            # ⚠ 工作目錄指定為 adb 自己的資料夾，否則 daemon 會佔住暫存目錄。
            cwd=str(Path(self.adb).parent),
        )

    def _run_device(self, args: list[str], timeout: int | None = None) -> subprocess.CompletedProcess:
        """對裝置下指令。逾時轉成 AdbError，排程會當成連線中斷處理。"""
        try:
            return self._run(["-s", self.serial, *args], timeout=timeout)
        except subprocess.TimeoutExpired:
            raise AdbError(f"模擬器沒有回應：adb {' '.join(args[:2])} 超過 "
                           f"{timeout or self.timeout} 秒") from None

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
        """先啟動 adb server，再做真正的連線；起不來也不拋錯。

        ⚠ 不可省略：冷啟動可能要十幾秒，會吃掉 `adb connect` 的逾時時間。
        """
        try:
            self._run(["start-server"], timeout=max(self.timeout, 60))
        except subprocess.TimeoutExpired:
            log.warning("adb server 啟動逾時，仍會試著連線")

    def connect(self) -> None:
        """建立連線並驗證裝置規格。

        ⚠ `serial: auto` 不會建立連線，所以有填 host/port 時一律先 `adb connect`。
        """
        self._ensure_server()
        self._try_connect()

        if not self.is_online():
            # 5037 埠上的舊 daemon 狀態壞掉時，重啟 server 就會恢復。
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
        try:
            self._verify_spec()
        except AdbError as e:
            # ⚠ 連線閒置一整晚之後 adb 仍回報在線，第一個指令才收到「error: closed」，斷開重連。
            log.warning("裝置連線已失效，重新連線：%s", str(e).strip().splitlines()[-1])
            self._disconnect()
            self._try_connect()
            self._verify_spec()

    def _disconnect(self) -> None:
        """斷開這台裝置的連線，失敗也沒關係。"""
        try:
            self._run(["disconnect", self.serial], timeout=self.timeout)
        except subprocess.TimeoutExpired:
            pass

    def _try_connect(self) -> None:
        """依設定建立連線（見 connect）。"""
        if self.serial == "auto":
            if self.cfg.device.port:
                self._network_connect(f"{self.cfg.device.host}:{self.cfg.device.port}")
            self._resolve_auto()
        elif self.cfg.device.is_network:
            self._network_connect(self.serial)

    def _network_connect(self, target: str) -> None:
        """對網路位址執行 adb connect，結果寫成中文。連不上不拋錯，由 is_online() 判斷。"""
        try:
            proc = self._run(["connect", target], timeout=self.timeout)
        except subprocess.TimeoutExpired:
            log.warning("連線 %s 逾時（%d 秒）", target, self.timeout)
            return
        out = proc.stdout.decode("utf-8", "ignore").strip()
        # adb 的原始輸出是英文，正常時寫中文結論，異常時附原文
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
        """檢查解析度與 DPI，不符只警告不中斷。規格正常時只在第一次寫紀錄。"""
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
        """擷取一張畫面，回傳 OpenCV BGR 影像。

        先用原始格式（約 0.3 秒），格式不符時這台裝置改用 PNG（約 0.8 秒）。兩種格式的像素相同。
        """
        if self._raw_capture:
            img = self._screencap_raw()
            if img is not None:
                return img
            self._raw_capture = False
            log.debug("原始格式截圖無法解析，改用 PNG")
        return self._screencap_png()

    def _screencap_raw(self) -> np.ndarray | None:
        """原始格式：檔頭（寬、高、像素格式，新版多一個色彩空間）＋ RGBA 像素。

        像素格式不是 RGBA_8888（1）或長度不符就回傳 None。
        """
        raw = self._run_device(["exec-out", "screencap"]).stdout
        if len(raw) < 12:
            return None
        w, h, fmt = struct.unpack("<III", raw[:12])
        size = w * h * 4
        header = len(raw) - size
        if fmt != 1 or header not in (12, 16):
            return None
        rgba = np.frombuffer(raw, np.uint8, count=size, offset=header).reshape(h, w, 4)
        return cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGR)

    def _screencap_png(self) -> np.ndarray:
        """PNG 格式。用 `exec-out` 取得二進位輸出，避開 shell 重導向破壞 PNG。"""
        proc = self._run_device(["exec-out", "screencap", "-p"])
        raw = proc.stdout
        if not raw:
            raise AdbError(f"截圖失敗：{proc.stderr.decode('utf-8', 'ignore')}")

        if not raw.startswith(PNG_MAGIC):
            # 部分環境仍會做換行轉換，這裡還原
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

    def tap_repeat(self, x: int, y: int, times: int) -> None:
        """同一點連點，給加減鈕用，不帶抖動。

        ⚠ 全部放進一個 shell 指令：逐次呼叫 adb 每下要 1 秒，引擎會判定畫面靜止而按返回鍵。
        """
        if times <= 0:
            return
        # 每下之間停 0.2 秒：不間隔地送，2 下會被吃掉 1 下。
        self.shell("; sleep 0.2; ".join([f"input tap {x} {y}"] * times),
                   timeout=max(20, times * 2))
        log.debug("tap (%d, %d) ×%d", x, y, times)
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
        # pidof 輸出的是 PID，只看有沒有輸出
        out = self.shell(f"pidof {package} || true").strip()
        return any(token.isdigit() for token in out.split())
