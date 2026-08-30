"""統一的日誌設定：同時輸出到終端機與 logs/assistant.log。

紀錄是這個專案最主要的除錯依據——實機跑起來之後，能看到的就只有這些字。
所以格式刻意做成全繁體中文、欄位對齊，掃過去就知道是誰在講話、講什麼。
"""

from __future__ import annotations

import logging
import sys
import unicodedata
from pathlib import Path
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler

from .config import LOG_DIR

_configured = False

# 紀錄保留幾天。一天的量不大（錄製的逐幀早就不寫進檔案了），留一個月方便回頭
# 對照「那天是不是也這樣」。
LOG_KEEP_DAYS = 30

# 等級與模組名都翻成中文。模組名是給人看的「誰在講話」，不是識別碼。
# ⚠ 新增模組時要一起加進來，而且模組取 logger 時要用這裡的鍵（不是 __name__，
#   那會是 core.xxx 而對不上，紀錄就露出英文名、欄位寬度也跟著歪掉）。
_LEVELS = {
    "DEBUG": "細節",
    "INFO": "資訊",
    "WARNING": "警告",
    "ERROR": "錯誤",
    "CRITICAL": "嚴重",
}
_MODULES = {
    "main": "主程式",
    "engine": "引擎",
    "adb": "連線",
    "vision": "影像",
    "recorder": "錄製",
    "config": "設定",
    "ocr": "文字",
    "gui": "介面",
    "update": "更新",
}


# 模組名欄位的顯示寬度，含外面那組方括號。最長的「[主程式]」剛好 8 格。
_MODULE_WIDTH = 8

# 每一行長這樣：[2026-08-10 03:02:20] [資訊] [引擎]   訊息
_LINE_FORMAT = "[%(asctime)s] %(level_zh)s %(module_zh)s %(message)s"
_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def level_label(levelname: str) -> str:
    """英文等級名翻成中文。給 GUI 用，免得它去碰私有的對照表。"""
    return _LEVELS.get(levelname, levelname)


def module_label(name: str) -> str:
    """logger 名稱翻成中文的「誰在講話」。"""
    return _MODULES.get(name, name)


def is_known_module(name: str) -> bool:
    """這個 logger 名稱是不是專案自己的模組。

    給介面過濾第三方紀錄用：handler 掛在 root logger 上會收到所有人的訊息，
    而 pywebview 自己就用 logging（debug 模式下每個事件寫一行）。判斷交給這裡，
    呼叫端就不必去碰 `_MODULES`，也不會多出第二份要維護的清單。
    """
    return name in _MODULES


def display_width(text: str) -> int:
    """字串在終端機佔幾個半寬字元。

    中文與全形標點在等寬字型下佔兩格，而 `str.ljust` 是按「字元數」補空格，
    所以「[連線]」和「[主程式]」用 ljust 補完寬度並不一致，欄位就會歪掉。
    """
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)


def pad(text: str, width: int) -> str:
    """把字串補到指定的**顯示**寬度。"""
    return text + " " * max(0, width - display_width(text))


def pretty_seconds(seconds: float) -> str:
    """把秒數寫成好讀的形式：45 秒 / 3 分 12 秒 / 1 小時 05 分。

    ⚠ 紀錄與任務卡共用這一份。分開寫的下場是同一輪在兩個地方長得不一樣——
      實測 39 秒的那一輪，紀錄寫「39 秒」而卡片寫「0 分 39 秒」。
    """
    s = int(seconds)
    if s < 60:
        return f"{s} 秒"
    if s < 3600:
        return f"{s // 60} 分 {s % 60:02d} 秒"
    return f"{s // 3600} 小時 {s % 3600 // 60:02d} 分"


class ChineseFormatter(logging.Formatter):
    """把等級與模組名換成中文，並按顯示寬度對齊欄位。"""

    def format(self, record: logging.LogRecord) -> str:
        level = _LEVELS.get(record.levelname, record.levelname)
        record.level_zh = f"[{level}]"
        module = _MODULES.get(record.name, record.name)
        record.module_zh = pad(f"[{module}]", _MODULE_WIDTH)
        return super().format(record)


def _force_utf8_output() -> None:
    """把終端機輸出改成 UTF-8。

    Windows 的主控台是 UTF-8 的，但**輸出一旦被導向檔案或管線就會退回 cp950**，
    而 cp950 沒有「≥」這個字（門檻說明用得到）——`explain` 會直接
    UnicodeEncodeError 當掉，紀錄那邊則是每筆量測都印一次 logging 錯誤。

    errors="replace" 是刻意的：顯示不出來的字寧可變成「?」，也不要為它中斷執行。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError, ValueError):
            pass        # 不是可重設的檔案物件（例如被接管過的 stdout），跳過


def formatter() -> logging.Formatter:
    """對外提供同一份格式器，讓額外掛上的 handler（GUI）長得跟紀錄檔一樣。"""
    return ChineseFormatter(_LINE_FORMAT, _TIME_FORMAT)


def _dated_name(default: str) -> str:
    """輪替後的檔名：`assistant.log.2026-08-23` → `assistant-2026-08-23.log`。

    ⚠ 副檔名要留在最後。預設的命名會產生 `.log.2026-08-23`，Windows 認不得那個
      副檔名——雙擊時會問「要用什麼開啟」，而那正是使用者想回頭查那天紀錄的時候。
    """
    base, _, stamp = default.rpartition(".")
    return str(Path(base).with_name(f"assistant-{stamp}.log"))


def setup(level: int = logging.INFO) -> None:
    global _configured
    if _configured:
        return

    _force_utf8_output()
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    fmt = formatter()

    handlers: list[logging.Handler] = []
    # 視窗模式（PyInstaller --windowed）沒有主控台，stdout 是 None。
    # 那種情況下建 StreamHandler 會在每次寫紀錄時炸在 emit 裡，只能不建。
    if sys.stdout is not None:
        stream = logging.StreamHandler(sys.stdout)
        stream.setFormatter(fmt)
        handlers.append(stream)

    # 每天午夜換一個檔，不是每 2MB 換一個。
    #
    # ⚠ 按大小輪替的切點是**任意的**：要查「8/23 那天發生什麼」得自己翻三個檔案
    #   對時間，而忙碌的一天還會把前幾天整段擠出保留範圍。按日期切，檔名本身就是
    #   索引。
    # ⚠ 當天的仍然叫 assistant.log（介面的「開啟紀錄資料夾」、說明文件都指著它），
    #   跨過午夜才改名成 assistant-2026-08-23.log。
    # ⚠ 程式沒開著的時候不會換檔，但下次啟動時 handler 會照**檔案的修改時間**
    #   算出該不該換——所以「只在早上跑一小時」的用法也切得對。
    rotating = TimedRotatingFileHandler(
        LOG_DIR / "assistant.log", when="midnight",
        backupCount=LOG_KEEP_DAYS, encoding="utf-8",
    )
    rotating.namer = _dated_name
    rotating.setFormatter(fmt)
    handlers.append(rotating)

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers = handlers
    _configured = True


def attach(handler: logging.Handler) -> logging.Handler:
    """額外掛一個 handler（GUI 的紀錄面板），沿用同一份中文格式。

    刻意不取代原本的兩個：紀錄檔仍要照寫，出問題時那份才是可以事後翻的。
    """
    setup()
    handler.setFormatter(formatter())
    logging.getLogger().addHandler(handler)
    return handler


def detach(handler: logging.Handler) -> None:
    logging.getLogger().removeHandler(handler)


def get(name: str) -> logging.Logger:
    setup()
    return logging.getLogger(name)


def transient(module: str, message: str) -> str:
    """產生一行與正常紀錄同格式的「暫時訊息」，給終端機原地更新用。

    等待狀態每秒都在變，不適合寫進紀錄檔，但顯示格式必須和其他行一致，
    否則欄位會歪掉。等級寫「等待」以示區別。
    """
    stamp = datetime.now().strftime(_TIME_FORMAT)
    name = pad(f"[{_MODULES.get(module, module)}]", _MODULE_WIDTH)
    return f"[{stamp}] [等待] {name} {message}"


_vt_enabled: bool | None = None


def ansi_ready() -> bool:
    """終端機能不能用 ANSI 控制碼，順手把它打開。

    用途是「清除到行尾」（`\\x1b[K`），讓原地更新的等待訊息不必補空白去蓋掉殘字
    ——補空白會讓游標停在文字後面幾格，看起來像中間空了一段。

    Windows 10 之後的主控台支援 ANSI，但**預設是關的**，要自己設
    ENABLE_VIRTUAL_TERMINAL_PROCESSING（0x0004）。設不起來就回 False，
    呼叫端退回補空白——顯示醜一點，不值得為它中斷程式。
    """
    global _vt_enabled
    if _vt_enabled is not None:
        return _vt_enabled

    _vt_enabled = False
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)          # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            if kernel32.SetConsoleMode(handle, mode.value | 0x0004):
                _vt_enabled = True
    except Exception:
        pass
    return _vt_enabled


def set_console_title(text: str) -> None:
    """設定終端機視窗標題。

    打包成 EXE 之後，視窗標題預設是那一長串執行檔路徑，看不出在跑什麼。
    走 kernel32 而不是 `os.system("title ...")`，後者會另外開一個 cmd 行程。
    非 Windows 或呼叫失敗就安靜跳過——標題只是方便，不值得為它中斷程式。
    """
    try:
        import ctypes

        ctypes.windll.kernel32.SetConsoleTitleW(text)
    except Exception:
        pass


def _image_path(pid: int) -> str:
    """查一個行程的執行檔完整路徑，查不到就回傳空字串。"""
    import ctypes
    from ctypes import wintypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(32768)
        buf = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return buf.value
        return ""
    finally:
        kernel32.CloseHandle(handle)


def _console_window():
    """拿到「這個主控台是我們自己開的」時的視窗代號，否則回傳 None。

    ⚠ 一定要判斷主控台是誰的。從既有的 PowerShell 執行時，GetConsoleWindow()
      拿到的是**使用者那個終端機視窗**，藏掉等於讓他的視窗憑空消失。

    判斷方式是「附加在這個主控台上的行程，是不是全都是同一個執行檔」：

      雙擊 EXE       [子, 父]              都是本程式 → 是我們的，藏
      PowerShell 跑  [子, 父, powershell]  有別人 → 不藏
      python main.py [python, powershell]  有別人 → 不藏

    ⚠ 不能改用「GetConsoleProcessList 回傳 1」：PyInstaller 的 onefile 是父子
      兩個行程，兩個都附加在同一個主控台上，雙擊時回傳的是 2。
    """
    try:
        import ctypes
        import sys

        kernel32 = ctypes.windll.kernel32
        hwnd = kernel32.GetConsoleWindow()
        if not hwnd:
            return None                 # --windowed 打包，本來就沒有主控台

        buf = (ctypes.c_uint32 * 16)()
        count = kernel32.GetConsoleProcessList(buf, 16)
        if count < 1:
            return None

        me = (sys.executable or "").lower()
        if not me:
            return None
        for pid in buf[:count]:
            path = _image_path(pid).lower()
            # 查不到就當成別人的，寧可不藏也不要弄不見使用者的終端機
            if path != me:
                return None
        return hwnd
    except Exception:
        return None


MB_ERROR = 0x10
MB_INFO = 0x40


def message_box(title: str, text: str, icon: int = MB_ERROR) -> None:
    """跳一個系統彈窗。

    `--windowed` 打包後若連圖形介面都載入失敗，就沒有任何地方可以說明原因了
    （沒有主控台，視窗也起不來）。這是最後一條能讓人看到訊息的路。

    `icon` 用 `MB_ERROR` / `MB_INFO`——網頁介面沒有自己的對話框元件，「已經在
    執行中」這種說明也走這裡，那不是錯誤。
    """
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, text, title, icon)
    except Exception:
        pass


def attach_console() -> bool:
    """接上呼叫者的主控台，回傳「有沒有接到」。

    執行檔是用 `--windowed` 打包的：雙擊時完全不會有黑視窗（onefile 的
    bootloader 解壓那 2～3 秒也一樣，那段時間我們的程式根本還沒開始跑，
    再早的 hide_console() 都追不上——這是換打包方式而不是繼續修藏視窗的原因）。

    代價是命令列模式預設沒有地方可以輸出：`--windowed` 下 `sys.stdout` 是 None。
    `AttachConsole(ATTACH_PARENT_PROCESS)` 借用呼叫者那個主控台，再把 stdout /
    stderr 綁回去，`EXE run` 在 PowerShell 裡就照樣看得到輸出。

    三種啟動方式的結果：
      雙擊 EXE            沒有父主控台 → 接不到，回 False（本來就不需要）
      PowerShell 跑 run   接到使用者的終端機 → 輸出照常
      工作排程器跑 run    沒有父主控台 → 接不到，輸出走 logs/assistant.log

    ⚠ 接不到不是錯誤，紀錄檔本來就一直在寫。所以失敗一律安靜跳過。
    """
    if sys.stdout is not None:
        return False        # 未打包、或 --console 打包，本來就有輸出可用
    try:
        import ctypes

        ATTACH_PARENT_PROCESS = -1
        if not ctypes.windll.kernel32.AttachConsole(ATTACH_PARENT_PROCESS):
            return False
    except Exception:
        return False

    # 接上主控台之後 sys.stdout 仍是 None，要自己綁到主控台的輸出裝置。
    # buffering=1（行緩衝）是必要的：等待中的進度行靠 \r 原地更新，
    # 積在緩衝區裡就看不到了。
    for name, dev, mode in (("stdout", "CONOUT$", "w"),
                            ("stderr", "CONOUT$", "w"),
                            ("stdin", "CONIN$", "r")):
        try:
            setattr(sys, name, open(dev, mode, encoding="utf-8",
                                    errors="replace", buffering=1))
        except OSError:
            pass            # 綁不上就算了，紀錄檔仍然照寫
    return True


def hide_console() -> bool:
    """把自己的主控台視窗藏起來，回傳「有沒有真的藏到」。

    雙擊 EXE 開圖形介面時，那個空的黑視窗很難看。回傳值是給呼叫端用的——
    藏起來之後若還要印錯誤訊息給人看，得先 show_console() 放回來。
    """
    hwnd = _console_window()
    if hwnd is None:
        return False
    try:
        import ctypes

        ctypes.windll.user32.ShowWindow(hwnd, 0)      # SW_HIDE
        return True
    except Exception:
        return False


def show_console() -> None:
    """把藏起來的主控台放回來，用在「圖形介面開不起來，改用文字說明」。"""
    try:
        import ctypes

        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 5)  # SW_SHOW
    except Exception:
        pass
