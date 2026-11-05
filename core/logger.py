"""統一的日誌設定：同時輸出到終端機與 logs/assistant.log，全繁體中文、欄位對齊。"""

from __future__ import annotations

import logging
import sys
import unicodedata
from pathlib import Path
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler

from .config import LOG_DIR

_configured = False

# 紀錄保留天數
LOG_KEEP_DAYS = 30

# 等級與模組名的中文對照。
# ⚠ 新增模組要加進來，模組取 logger 要用這裡的鍵（不是 __name__）。
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
    """英文等級名翻成中文。"""
    return _LEVELS.get(levelname, levelname)


def module_label(name: str) -> str:
    """logger 名稱翻成中文。"""
    return _MODULES.get(name, name)


def is_known_module(name: str) -> bool:
    """這個 logger 名稱是不是專案自己的模組，介面用來過濾第三方紀錄。"""
    return name in _MODULES


def display_width(text: str) -> int:
    """字串在終端機佔幾個半寬字元（中文與全形標點佔兩格）。"""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)


def pad(text: str, width: int) -> str:
    """把字串補到指定的顯示寬度。"""
    return text + " " * max(0, width - display_width(text))


def pretty_seconds(seconds: float) -> str:
    """把秒數寫成 45 秒 / 3 分 12 秒 / 1 小時 05 分。紀錄與任務卡共用。"""
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


def force_utf8_output() -> None:
    """把終端機輸出改成 UTF-8，tools/ 的命令列工具也會呼叫。

    輸出導向檔案或管線時 Windows 會退回 cp950，而 cp950 沒有「≥」。
    errors="replace"：顯示不出來的字變成「?」，不中斷執行。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError, ValueError):
            pass        # 不是可重設的檔案物件（例如被接管過的 stdout），跳過


def formatter() -> logging.Formatter:
    """對外提供同一份格式器，額外掛上的 handler 用。"""
    return ChineseFormatter(_LINE_FORMAT, _TIME_FORMAT)


def _dated_name(default: str) -> str:
    """輪替後的檔名：`assistant.log.2026-08-23` → `assistant-2026-08-23.log`。

    ⚠ 副檔名要留在最後，Windows 才認得。
    """
    base, _, stamp = default.rpartition(".")
    return str(Path(base).with_name(f"assistant-{stamp}.log"))


def setup(level: int = logging.INFO) -> None:
    global _configured
    if _configured:
        return

    force_utf8_output()
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    fmt = formatter()

    handlers: list[logging.Handler] = []
    # 視窗模式（PyInstaller --windowed）的 stdout 是 None，不建 StreamHandler。
    if sys.stdout is not None:
        stream = logging.StreamHandler(sys.stdout)
        stream.setFormatter(fmt)
        handlers.append(stream)

    # 每天午夜換一個檔。當天的叫 assistant.log，跨過午夜才改名。
    # 程式沒開著時不會換檔，下次啟動時依檔案修改時間判斷。
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
    """額外掛一個 handler（介面的紀錄面板），沿用同一份中文格式。紀錄檔照常寫。"""
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
    """產生一行與正常紀錄同格式的暫時訊息，給終端機原地更新用，等級寫「等待」。"""
    stamp = datetime.now().strftime(_TIME_FORMAT)
    name = pad(f"[{_MODULES.get(module, module)}]", _MODULE_WIDTH)
    return f"[{stamp}] [等待] {name} {message}"


_vt_enabled: bool | None = None


def ansi_ready() -> bool:
    """啟用 ANSI 控制碼（0x0004），回傳是否可用。設不起來時呼叫端改為補空白。"""
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
    """設定終端機視窗標題，走 kernel32，呼叫失敗就略過。"""
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
    """主控台是這個程式自己開的就回傳視窗代號，否則回傳 None。

    判斷方式是附加在主控台上的行程是否全都是同一個執行檔：

      雙擊 EXE       [子, 父]              都是本程式 → 是自己的
      PowerShell 跑  [子, 父, powershell]  有別人 → 不是
      python main.py [python, powershell]  有別人 → 不是

    ⚠ 不可改用「GetConsoleProcessList 回傳 1」：onefile 是父子兩個行程。
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
            # 查不到就當成別人的
            if path != me:
                return None
        return hwnd
    except Exception:
        return None


MB_ERROR = 0x10
MB_INFO = 0x40


def message_box(title: str, text: str, icon: int = MB_ERROR) -> None:
    """顯示系統訊息框。`icon` 用 `MB_ERROR` / `MB_INFO`。

    用於介面載入失敗（沒有主控台也沒有視窗）與「已經在執行中」的說明。
    """
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, text, title, icon)
    except Exception:
        pass


def attach_console() -> bool:
    """接上呼叫者的主控台，回傳是否接到。`--windowed` 打包的 sys.stdout 是 None。

      雙擊 EXE            沒有父主控台 → 回傳 False
      PowerShell 跑 run   接到使用者的終端機
      工作排程器跑 run    沒有父主控台，輸出走 logs/assistant.log

    接不到不是錯誤，一律略過。
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

    # 把 stdout 綁到主控台。buffering=1：進度行靠 \r 原地更新，不可積在緩衝區。
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
    """隱藏自己的主控台視窗，回傳是否隱藏。之後要印錯誤訊息前先呼叫 show_console()。"""
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
    """顯示被隱藏的主控台，用於介面開不起來、改用文字說明時。"""
    try:
        import ctypes

        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 5)  # SW_SHOW
    except Exception:
        pass
