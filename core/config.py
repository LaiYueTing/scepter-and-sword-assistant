"""設定檔載入與存取。"""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass, field, fields
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml

# 打包成單檔 EXE 後有兩個根目錄，開發時兩者都是專案根目錄：
#
#   ROOT   ─ EXE 所在的目錄，放設定檔與 logs。
#   BUNDLE ─ 打包內容解壓到的暫存目錄（sys._MEIPASS），放腳本、模板、adb。
#            ⚠ 唯讀，而且每次執行的路徑都不同。
#
if getattr(sys, "frozen", False):
    ROOT = Path(sys.executable).resolve().parent
    BUNDLE = Path(getattr(sys, "_MEIPASS", ROOT))
else:
    ROOT = BUNDLE = Path(__file__).resolve().parent.parent


def resource_file(kind: str, filename: str) -> Path:
    """資源檔（模板、腳本）的位置：EXE 旁邊有同名檔案就優先用那份。

    ⚠ 逐檔判斷，不是整個目錄二選一，否則一個自製模板會遮蔽全部內建模板。
    """
    external = ROOT / kind / filename
    return external if external.is_file() else BUNDLE / kind / filename


def resource_files(kind: str, pattern: str) -> list[Path]:
    """列出某類資源的所有檔案，EXE 旁邊的同名檔案優先（覆蓋內建的那份）。"""
    found: dict[str, Path] = {}
    for base in (BUNDLE / kind, ROOT / kind):      # 後者覆蓋前者
        if base.is_dir():
            for p in sorted(base.glob(pattern)):
                found[p.name] = p
    return sorted(found.values(), key=lambda p: p.name)


# 目前版本，由 tools/bump_version.py 同步，與 version_info.txt 一致。
VERSION = "1.6.0"


class ConfigError(RuntimeError):
    """設定檔內容有問題，訊息會直接顯示給使用者。"""


@dataclass
class DeviceConfig:
    host: str = "127.0.0.1"
    port: int = 0
    width: int = 720
    height: int = 1280
    dpi: int = 320
    # 直接指定 adb 序號，優先於 host:port。多開時最好用這個。
    #   auto  自動選第一台連線中的裝置
    #   其他  模擬器序號，用 `python main.py devices` 查
    serial: str | None = None

    @property
    def target(self) -> str:
        """要連的目標，序號優先。"""
        if self.serial:
            return self.serial
        if not self.port:
            raise ConfigError(
                "config.yaml 沒有指定要連哪一台裝置。\n"
                "  同一台電腦執行：把 device.serial 設成 auto\n"
                "  跨機器連線　　：填入 device.host 與 device.port\n"
                "  （連接埠請看模擬器的設定；查不到就用介面上的「探索」）"
            )
        return f"{self.host}:{self.port}"

    @property
    def is_network(self) -> bool:
        """網路位址才需要 adb connect，本機序號不用。"""
        return ":" in self.target and not self.target.startswith("emulator-")


@dataclass
class AdbConfig:
    # adb 隨程式附帶，只有要改用系統或自訂 adb 時才需要設。
    path: str = "adb"
    timeout: int = 20


@dataclass
class RuntimeConfig:
    tick: float = 1.0                # 主迴圈每輪的間隔（秒）
    threshold: float = 0.85          # 模板比對的預設門檻
    post_tap_delay: float = 0.6      # 每次點擊後的固定等待，讓動畫跑完
    tap_jitter: int = 4              # 點擊座標的隨機抖動範圍（像素）
    # 啟動時是否補跑今天已過排定時刻的腳本。
    catch_up: bool = True
    # 下一個排定時刻在這麼多分鐘之內時，補跑先讓路。0 表示不讓路。
    catch_up_guard_minutes: int = 30


@dataclass
class UiConfig:
    """圖形介面的外觀，不影響腳本行為。"""

    # dark / light / system。system 跟著 Windows 的深淺色設定走
    theme: str = "system"
    # 形狀語彙。目前只有 flat 一套，認不得的值會退回它
    shape: str = "flat"
    # ⚠ 這兩個已無作用，保留是為了讓寫過它們的 config.yaml 載入時不出警告。
    backdrop: str = "none"
    mica: bool = False


WEEKDAY_NAMES = ["週一", "週二", "週三", "週四", "週五", "週六", "週日"]
# 星期一是 0，和 `datetime.weekday()` 對齊。接受中英與簡寫。
WEEKDAYS = {name: i for i, name in enumerate(
    ["一", "二", "三", "四", "五", "六", "日"])}
WEEKDAYS.update({"天": 6})
WEEKDAYS.update({name: i for i, name in enumerate(
    ["mon", "tue", "wed", "thu", "fri", "sat", "sun"])})
WEEKDAYS.update({name: i for i, name in enumerate(
    ["monday", "tuesday", "wednesday", "thursday",
     "friday", "saturday", "sunday"])})


def _as_list(value) -> list:
    return [value] if isinstance(value, str) else list(value or [])


def _hhmm(item, where: str, field_name: str) -> tuple[int, int]:
    """把「HH:MM」拆成 (時, 分)。錯誤訊息指名腳本與欄位。"""
    try:
        hh, mm = (int(v) for v in str(item).strip().split(":"))
    except ValueError:
        raise ConfigError(
            f"腳本「{where}」的 {field_name} 要寫成 HH:MM，收到：{item!r}"
        ) from None
    if not (0 <= hh < 24 and 0 <= mm < 60):
        raise ConfigError(f"腳本「{where}」的 {field_name} 有不存在的時間：{item!r}")
    return hh, mm


@dataclass
class TaskConfig:
    """一個要執行的腳本，以及它的排程（每日或每週固定某天）。"""

    name: str
    enabled: bool = True
    repeat: int = 0                                          # 0 = 不限次數
    daily_at: str | list[str] = field(default_factory=list)  # 空 = 不排程
    # 每週固定某天的時刻，寫成「週一 08:00」。
    weekly_at: str | list[str] = field(default_factory=list)
    # 錯過今天的時刻之後是否補跑。
    # ⚠ 只影響 `_missed_today`，不影響上一輪執行期間經過的那一格（`_passed_during`）。
    catch_up: bool = True

    @property
    def times(self) -> list[tuple[int, int]]:
        """每日的排定時刻，已排序去重，格式錯誤在這裡報錯。"""
        return sorted({_hhmm(item, self.name, "daily_at")
                       for item in _as_list(self.daily_at)})

    @property
    def weekly(self) -> list[tuple[int, int, int]]:
        """每週的排定時刻 (星期, 時, 分)，星期一是 0。"""
        found: set[tuple[int, int, int]] = set()
        for item in _as_list(self.weekly_at):
            text = str(item).strip().replace("　", " ")
            day, _, clock = text.partition(" ")
            weekday = WEEKDAYS.get(day.strip().lower().removeprefix("週")
                                   .removeprefix("星期"))
            if weekday is None or not clock.strip():
                raise ConfigError(
                    f"腳本「{self.name}」的 weekly_at 要寫成「週一 08:00」，"
                    f"收到：{item!r}")
            hh, mm = _hhmm(clock, self.name, "weekly_at")
            found.add((weekday, hh, mm))
        return sorted(found)

    def times_on(self, day: date) -> list[tuple[int, int]]:
        """那一天實際會執行的時刻：每日的，加上星期相符的每週時刻。"""
        weekday = day.weekday()
        return sorted(set(self.times)
                      | {(hh, mm) for wd, hh, mm in self.weekly if wd == weekday})

    def next_run(self, now: datetime | None = None) -> datetime | None:
        """下一個該執行的時刻。已經過去的時間點算到下一輪；沒排程則回 None。"""
        now = now or datetime.now()
        candidates = []
        for hh, mm in self.times:
            target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if target <= now:
                target += timedelta(days=1)
            candidates.append(target)
        for weekday, hh, mm in self.weekly:
            target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            target += timedelta(days=(weekday - now.weekday()) % 7)
            if target <= now:
                target += timedelta(days=7)
            candidates.append(target)
        return min(candidates) if candidates else None

    def describe(self) -> str:
        """給紀錄用的可讀說明，例如「每日 12:33、21:03」。"""
        parts = []
        if self.times:
            parts.append("每日 " + "、".join(f"{hh:02d}:{mm:02d}"
                                             for hh, mm in self.times))
        if self.weekly:
            parts.append("、".join(f"{WEEKDAY_NAMES[wd]} {hh:02d}:{mm:02d}"
                                   for wd, hh, mm in self.weekly))
        return "，".join(parts) or "不排程"


@dataclass
class Config:
    device: DeviceConfig = field(default_factory=DeviceConfig)
    adb: AdbConfig = field(default_factory=AdbConfig)
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    ui: UiConfig = field(default_factory=UiConfig)
    tasks: list[TaskConfig] = field(default_factory=list)
    # 腳本開關，所有腳本共用。規則用 when_option 綁定。
    options: dict[str, bool] = field(default_factory=dict)
    # 這次執行才剛從範本建立設定檔，裝置資訊還沒填。
    is_new: bool = False
    path: Path | None = None

    @property
    def enabled_tasks(self) -> list[TaskConfig]:
        return [t for t in self.tasks if t.enabled]

    def task_of(self, name: str) -> TaskConfig:
        """依名稱取出腳本設定。設定檔沒列到的（-t 指定）就給一份預設的。"""
        for t in self.tasks:
            if t.name == name:
                return t
        return TaskConfig(name=name)

    @classmethod
    def load(cls, path: Path | str | None = None) -> "Config":
        path = Path(path) if path else ROOT / "config.yaml"

        # 設定檔留在 EXE 外面，第一次執行時從內建範本複製。
        is_new = False
        if not path.exists():
            example = ROOT / "config.example.yaml"
            if not example.exists():
                example = BUNDLE / "config.example.yaml"
            if example.exists() and path == ROOT / "config.yaml":
                shutil.copyfile(example, path)
                is_new = True
            else:
                raise FileNotFoundError(f"找不到設定檔：{path}")

        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

        # 每個區段都可以省略，省略就用預設值。
        cfg = cls(
            device=_section(DeviceConfig, raw.get("device"), "device"),
            adb=_section(AdbConfig, raw.get("adb"), "adb"),
            runtime=_section(RuntimeConfig, raw.get("runtime"), "runtime"),
            ui=_section(UiConfig, raw.get("ui"), "ui"),
            tasks=_load_tasks(raw),
            options=_load_options(raw),
            is_new=is_new,
            path=path,
        )
        return cfg


def _section(cls, raw: dict | None, where: str):
    """建立一個設定區段，認不出來的欄位略過並留一筆警告。"""
    data = raw or {}
    known = {f.name for f in fields(cls)}
    unknown = sorted(set(data) - known)
    if unknown:
        from . import logger      # 延遲載入：logger 反過來要用這裡的 LOG_DIR
        logger.get("config").warning(
            "設定檔的 %s 有認不出來的項目，已略過：%s", where, "、".join(unknown))
    return cls(**{k: v for k, v in data.items() if k in known})


def _load_tasks(raw: dict) -> list[TaskConfig]:
    """讀出要執行的腳本清單。

    新格式是 tasks: 清單；舊格式是「task: 名稱」＋「schedule: 時間」，同樣接受。
    """
    if raw.get("tasks"):
        items = raw["tasks"]
        if isinstance(items, dict):        # 也接受 {name: {...}} 的寫法
            items = [{"name": k, **(v or {})} for k, v in items.items()]
        return [_section(TaskConfig, item, f"tasks 的「{item.get('name')}」")
                for item in items]

    old = raw.get("task") or {}
    sched = raw.get("schedule") or {}
    return [TaskConfig(
        name=old.get("name", "dungeon"),
        repeat=int(old.get("repeat", 0)),
        # 舊格式的 enabled 關閉時等於沒有排程
        daily_at=sched.get("daily_at", []) if sched.get("enabled") else [],
    )]


def _load_options(raw: dict) -> dict[str, bool]:
    """腳本開關：頂層 options，或舊格式的 task.options。"""
    if raw.get("options") is not None:
        return raw["options"] or {}
    return (raw.get("task") or {}).get("options") or {}


# 紀錄目錄，在 EXE 旁邊。
# ⚠ `SSA_LOG_DIR` 給測試用，避免測試內容寫進真正的 assistant.log。
LOG_DIR = Path(os.environ.get("SSA_LOG_DIR") or (ROOT / "logs"))
TEMPLATE_OUT_DIR = ROOT / "templates"   # crop 產生的新模板寫這裡（BUNDLE 寫不得）
SAMPLE_DIR = ROOT / "samples"           # 回歸測試樣本，開發用，不打包
