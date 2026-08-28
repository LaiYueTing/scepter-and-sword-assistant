"""探索可用的模擬器，讓使用者不必自己去模擬器的設定裡翻 ADB 連接埠。

`adb devices` 只列得出**已經連上**的裝置，跨機器的模擬器在 `adb connect`
之前不會出現在那份清單裡，所以要主動去找。

⚠ 放在 core/ 而不是 gui/：命令列的 `devices` 與圖形介面的「探索」共用這一份，
  不要各做一套。

流程分三段，慢的那段盡量少做：

1. `adb devices`——已經連上的，最可靠，零成本。
2. **TCP 探測**候選的 host:port。純 socket、逾時 0.3 秒、並行送出，
   所以掃幾十個組合也只花不到一秒。
3. 只對「探測得通、但還沒連上」的做 `adb connect`——這一步才會真的花時間
   （逾時要自己壓短，預設的 20 秒乘上候選數量會讓介面像當掉）。

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

# MuMu Player 的 ADB 埠：12 代預設 16384，每多開一個實例 +32。實測使用者那台是
# 16480（= 16384 + 32×3）。掃前 8 個實例就涵蓋絕大多數人的多開情況。
_MUMU_PORTS = [16384 + 32 * i for i in range(8)]
# 其他常見的：MuMu 舊版與通用 Android 走 7555 / 5555，順手把夜神、雷電也帶上，
# 反正 TCP 探測很便宜。
_OTHER_PORTS = [7555, 5555, 62001, 21503, 5554]

CANDIDATE_PORTS = _MUMU_PORTS + _OTHER_PORTS

# 這幾個位址的掃描不出網卡，所以不受「不要自動掃」的限制
_LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")


# adb 回報的狀態 → 中文。介面與紀錄全繁體，這一欄原本是唯一漏掉的英文。
#
# ⚠ 認不得的狀態要**原樣寫出來**，不要吞掉或寫成「未知」。adb 還會回
#   authorizing、no permissions 這些，翻不到的至少要讓人拿原文去搜。
_STATE_TEXT = {
    "device": "正常",
    "offline": "離線",
    "unauthorized": "未授權",
    "authorizing": "授權中",
    "connecting": "連線中",
}

# 只有紀錄寫得下這一句。下拉與 tooltip 的空間有限，而「離線」兩個字已經夠讓人
# 知道不能用了；真的要查原因才需要知道「連得上但沒回應」是什麼意思。
_STATE_HINT = {
    "offline": "adb 連得上但裝置沒有回應，通常是模擬器還沒開完，或這是一筆舊的連線",
    "unauthorized": "模擬器那邊要按下「允許 USB 偵錯」",
}


def state_text(state: str) -> str:
    """把 adb 的狀態字串換成中文，認不得的原樣回傳。"""
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
        """規格符不符合腳本的硬性要求（模板全依 720x1280 裁）。

        ⚠ 兩邊都轉成字串再比。`dpi` 是從 adb 的輸出解析出來的字串，但呼叫端
          給的是設定檔裡的整數——只轉一邊的話 320 對不上 "320"，會把規格正確的
          裝置誤報成「解析度不符」。
        """
        return str(self.size) == str(want_size) and str(self.dpi) == str(want_dpi)

    def label(self, want_size: str = "", want_dpi: int = 0) -> str:
        """給下拉選單用的一行說明。"""
        return "　".join(self._bits(want_size, want_dpi))

    def describe(self, want_size: str = "", want_dpi: int = 0) -> str:
        """帶欄位名稱的說明，給紀錄用。

        紀錄裡只有一長串「192.168.1.108:16480 SM-S938U 720x1280 / 320dpi」的話，
        要自己分辨哪一段是什麼。標上名稱就不必猜——而且位址有兩種形態，
        跨機器是 IP:埠、同一台是 adb 序號，講清楚是哪一種比較好懂。
        """
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
        """下拉清單與 tooltip 共用的多行版本，**固定兩行**。

        ⚠ 不要把 `label()` 直接拿去當下拉的標籤或 tooltip。那一行很長（旗標＋
          序號＋型號＋解析度），而清單與 tooltip 都是由 view 畫的、會沿用它的
          省略設定——結果被吃掉中間變成「192.168.1.108:1...0x1280 / 320dpi」，
          最重要的埠號與解析度剛好都在省略號裡。

        ⚠ **分成兩行而不是四行，也不加欄位名稱。** 第一行是「要連去哪裡」（旗標
          與位址），第二行是「那是什麼機器」（型號與解析度）——這兩件事的答案
          從格式就看得出來，補上「IP：」「型號：」只會讓每一項變成兩倍長，而
          下拉裡通常不只一台。帶欄位名的版本是 `describe()`，那是給紀錄用的：
          紀錄是一整片文字，沒有版面可以分欄。
        """
        bits = self._bits(want_size, want_dpi)
        flag = bits[0] if bits and bits[0].startswith("［") else ""
        rest = bits[1:] if flag else bits
        head = (flag + rest[0]) if rest else flag
        return chr(10).join([x for x in (head, "・".join(rest[1:])) if x])

    def _bits(self, want_size: str, want_dpi: int) -> list[str]:
        """下拉與 tooltip 共用的欄位，**旗標排最前面**。

        ⚠ 旗標不能排在尾端。下拉收起來時寬度有限（見 DevicePanel 的說明），
          而序號本身就佔掉大半——排在後面的話「［離線］」正好落在被切掉的那一段，
          「這台不能用」變成最看不見的資訊。沒有旗標的正常裝置不受影響。
        """
        bits = []
        if self.state != "device":
            bits.append(f"［{state_text(self.state)}］")
        elif want_size and not self.matches_spec(want_size, want_dpi):
            # 解析度不對的話整套模板都會比不中，這比「連得上」重要得多
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
    """純 socket 探測。比 adb connect 快兩個數量級，用來篩掉不存在的組合。"""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def probe_ports(host: str, ports: list[int] | None = None,
                timeout: float = 0.3) -> list[int]:
    """回傳 host 上有在監聽的候選埠。

    ⚠ 最後手段，只在「不知道埠號」時呼叫。對同一台主機連敲十幾個埠，在防毒的
      IDS 眼裡就是連接埠掃描，會被封鎖到整台機器 TCP 全滅（見 CLAUDE.md）。
    ⚠ 執行緒 8 條就好：32 條會讓十幾個 SYN 幾乎同時到達，那個突發特徵正是 IDS
      在看的，而 8 條只慢 0.3 秒。
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

    `device` 是一個已建立的 core.adb.Device（只借它的 adb 路徑與設定，
    不會用它去操作畫面）。`hosts` 沒給時，掃「設定檔裡的 host」與本機。

    `deep` 決定**遠端**主機要不要做多埠掃描：

        True   掃候選埠清單，用來找出「埠號到底是多少」。使用者按下「探索」
               屬於這一種——那是明確的意思表示。
        False  只敲設定檔裡那一個埠。自動觸發的探索（開視窗時）走這條。

    ⚠ 自動探索**不可以**用 deep=True。對同一台主機連敲十幾個埠會被防毒判定成
      連接埠掃描而封鎖整台機器，而開視窗是使用者隨手就會做很多次的動作——
      實測三分鐘內六次就中了（見 CLAUDE.md）。

    ⚠ 本機 127.0.0.1 不受這個限制，照樣掃。loopback 不出網卡，對方的防毒
      看不到，而第一次執行的使用者正是靠它把本機模擬器找出來的。
    """
    adb = str(device.adb)

    # ---- 1. 已經連上的 ----
    found: dict[str, Found] = {}
    try:
        for serial, state in device.list_devices():
            found[serial] = Found(serial=serial, state=state)
    except Exception as e:                       # adb server 起不來也不該中斷探索
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

    # ⚠ 設定檔已經指名埠號的那一台只敲那一個埠。掃描是給「還不知道埠號」用的，
    #   而設定好之後每次開視窗都會自動探索一次（見 CLAUDE.md）。
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
