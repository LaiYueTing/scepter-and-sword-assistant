"""探索可用的模擬器，命令列的 `devices` 與介面的「探索」共用。

分三段，慢的那段盡量少做：

1. `adb devices`：已經連上的。
2. TCP 探測候選的 host:port：純 socket、逾時 0.3 秒、並行送出。
3. 只對探測得通、還沒連上的做 `adb connect`，逾時壓短。

⚠ 全程唯讀：只有 connect / getprop / wm size，不會點擊或啟動任何 App。
"""

from __future__ import annotations

import re
import socket
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from core import logger

log = logger.get("adb")

# MuMu Player 的 ADB 埠：12 代預設 16384，每多開一個實例 +32（16480 = 16384 + 32×3）。
# 掃前 8 個實例，涵蓋常見的多開數量。
_MUMU_PORTS = [16384 + 32 * i for i in range(8)]
# 其他常見的埠：MuMu 舊版與通用 Android（7555 / 5555）、夜神、雷電。
_OTHER_PORTS = [7555, 5555, 62001, 21503, 5554]

CANDIDATE_PORTS = _MUMU_PORTS + _OTHER_PORTS

# 這幾個位址的掃描不出網卡，可以掃多埠
_LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")


# adb 回報的狀態 → 中文。⚠ 無法辨識的狀態原樣顯示。
_STATE_TEXT = {
    "device": "正常",
    "offline": "離線",
    "unauthorized": "未授權",
    "authorizing": "授權中",
    "connecting": "連線中",
}

# 只寫在紀錄裡的狀態補充說明。
_STATE_HINT = {
    "offline": "adb 連得上但裝置沒有回應，通常是模擬器還沒開完，或這是一筆舊的連線",
    "unauthorized": "模擬器那邊要按下「允許 USB 偵錯」",
}


def state_text(state: str) -> str:
    """把 adb 的狀態字串換成中文，無法辨識的原樣回傳。"""
    return _STATE_TEXT.get(state, state)


@dataclass
class Found:
    """探索到的一台裝置。"""

    serial: str
    state: str = "device"           # device / offline / unauthorized
    model: str = ""
    size: str = ""                  # 例如 720x1280
    dpi: str = ""
    connected_now: bool = False     # 是這次探索才連上的
    tags: list[str] = field(default_factory=list)

    @property
    def is_usable(self) -> bool:
        return self.state == "device"

    def matches_spec(self, want_size: str, want_dpi: int) -> bool:
        """規格是否符合腳本要求（模板全依 720x1280 裁）。⚠ 兩邊都轉成字串再比。"""
        return str(self.size) == str(want_size) and str(self.dpi) == str(want_dpi)

    def label(self, want_size: str = "", want_dpi: int = 0) -> str:
        """下拉選單用的單行說明。"""
        return "　".join(self._bits(want_size, want_dpi))

    def describe(self, want_size: str = "", want_dpi: int = 0) -> str:
        """帶欄位名稱的說明，給紀錄用。"""
        head = "IP" if ":" in self.serial and not self.serial.startswith("emulator-") \
            else "序號"
        parts = [f"{head}：{self.serial}"]
        if self.model:
            parts.append(f"型號：{self.model}")
        if self.size:
            spec = self.size + (f" / {self.dpi}dpi" if self.dpi else "")
            parts.append(f"解析度：{spec}")
        if self.state != "device":
            hint = _STATE_HINT.get(self.state)
            parts.append(f"狀態：{state_text(self.state)}"
                         + (f"（{hint}）" if hint else ""))
        elif want_size and not self.matches_spec(want_size, want_dpi):
            parts.append("⚠ 解析度不符，模板會全部比不中")
        return "　".join(parts)

    def detail(self, want_size: str = "", want_dpi: int = 0) -> str:
        """下拉清單與 tooltip 用的兩行說明：第一行旗標與位址，第二行型號與解析度。

        ⚠ 不可用 `label()`：單行會被省略號吃掉埠號與解析度。
        """
        bits = self._bits(want_size, want_dpi)
        flag = bits[0] if bits and bits[0].startswith("［") else ""
        rest = bits[1:] if flag else bits
        head = (flag + rest[0]) if rest else flag
        return chr(10).join([x for x in (head, "・".join(rest[1:])) if x])

    def _bits(self, want_size: str, want_dpi: int) -> list[str]:
        """下拉與 tooltip 共用的欄位。⚠ 旗標排最前面，收起來時不會被截掉。"""
        bits = []
        if self.state != "device":
            bits.append(f"［{state_text(self.state)}］")
        elif want_size and not self.matches_spec(want_size, want_dpi):
            # 解析度不符時模板全部比不中
            bits.append("［解析度不符］")
        bits.append(self.serial)
        if self.model:
            bits.append(self.model)
        if self.size:
            spec = f"{self.size}"
            if self.dpi:
                spec += f" / {self.dpi}dpi"
            bits.append(spec)
        return bits


def _tcp_open(host: str, port: int, timeout: float) -> bool:
    """純 socket 探測，用來篩掉不存在的組合。"""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def probe_ports(host: str, ports: list[int] | None = None,
                timeout: float = 0.3) -> list[int]:
    """回傳 host 上有在監聽的候選埠。

    ⚠ 只在不知道埠號時呼叫：連續探測同一台主機會被防毒的 IDS 判定成連接埠掃描（見 CLAUDE.md）。
    ⚠ 執行緒 8 條：32 條的突發特徵正是 IDS 偵測的對象，8 條只慢 0.3 秒。
    """
    ports = ports or CANDIDATE_PORTS
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = pool.map(lambda p: (p, _tcp_open(host, p, timeout)), ports)
        return [p for p, ok in results if ok]


def _query(adb: str, serial: str, prop: str, timeout: int) -> str:
    try:
        proc = subprocess.run(
            [str(adb), "-s", serial, "shell", prop],
            capture_output=True, timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return proc.stdout.decode("utf-8", "ignore").strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def describe(adb: str, serial: str, timeout: int = 6) -> tuple[str, str, str]:
    """查一台裝置的型號與螢幕規格，回傳 (型號, 解析度, dpi)。查不到就給空字串。"""
    model = _query(adb, serial, "getprop ro.product.model", timeout)
    size = ""
    m = re.search(r"(\d+x\d+)", _query(adb, serial, "wm size", timeout))
    if m:
        size = m.group(1)
    dpi = ""
    m = re.search(r"(\d+)", _query(adb, serial, "wm density", timeout))
    if m:
        dpi = m.group(1)
    return model, size, dpi


def scan(device, hosts: list[str] | None = None, connect_new: bool = True,
         timeout: float = 0.3, connect_timeout: int = 6,
         deep: bool = True) -> list[Found]:
    """探索可用的模擬器。

    `device` 是已建立的 core.adb.Device（只用它的 adb 路徑與設定）。
    `hosts` 沒給時，掃設定檔裡的 host 與本機。
    `deep` 決定遠端主機是否做多埠掃描：

        True   掃候選埠清單，使用者按下「探索」時使用。
        False  只敲設定檔裡的那一個埠，開視窗的自動探索使用。

    ⚠ 自動探索不可以用 deep=True。本機 127.0.0.1 不受限制（loopback 不出網卡）。
    """
    adb = str(device.adb)

    # ---- 1. 已經連上的 ----
    found: dict[str, Found] = {}
    try:
        for serial, state in device.list_devices():
            found[serial] = Found(serial=serial, state=state)
    except Exception as e:                       # adb server 起不來時繼續探索
        log.warning("列出已連線裝置失敗：%s", e)

    # ---- 2. TCP 探測 ----
    if hosts is None:
        hosts = []
        configured = (device.cfg.device.host or "").strip()
        if configured:
            hosts.append(configured)
        for local in ("127.0.0.1",):
            if local not in hosts:
                hosts.append(local)

    # ⚠ 設定檔已指名埠號的主機只敲那一個埠。
    configured_host = (device.cfg.device.host or "").strip()
    configured_port = int(device.cfg.device.port or 0)

    targets: list[str] = []
    for host in hosts:
        if (host == configured_host and configured_port
                and _tcp_open(host, configured_port, timeout)):
            ports = [configured_port]           # 一次連線，不構成掃描
        elif deep or host in _LOCAL_HOSTS:
            ports = probe_ports(host, timeout=timeout)
        else:
            ports = []                          # 自動探索不掃遠端主機
        for port in ports:
            target = f"{host}:{port}"
            if target not in found:
                targets.append(target)

    # ---- 3. 只對新發現的做 adb connect ----
    if connect_new:
        for target in targets:
            try:
                proc = subprocess.run(
                    [adb, "connect", target],
                    capture_output=True, timeout=connect_timeout,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                out = proc.stdout.decode("utf-8", "ignore")
                if "connected" in out:
                    found[target] = Found(serial=target, connected_now=True)
            except (OSError, subprocess.TimeoutExpired):
                continue        # 探測得通不代表是 adb，連不上就跳過

    # ---- 4. 補上型號與規格 ----
    for f in found.values():
        if f.is_usable:
            f.model, f.size, f.dpi = describe(adb, f.serial, timeout=connect_timeout)

    # 排序：能用的排前面，其中規格正確的又更前面
    want_size = f"{device.cfg.device.width}x{device.cfg.device.height}"
    want_dpi = device.cfg.device.dpi

    def rank(f: Found) -> tuple:
        return (not f.is_usable, not f.matches_spec(want_size, want_dpi), f.serial)

    return sorted(found.values(), key=rank)
