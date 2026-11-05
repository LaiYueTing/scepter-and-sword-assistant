"""腳本引擎：以 YAML 規則驅動的畫面狀態機。

運作方式是「看到什麼就做什麼」，而不是寫死一串固定操作：
每一輪抓一張畫面，由上而下檢查規則的觸發條件，執行第一條成立的規則。
這種寫法能應付突然跳出的對話框、斷線、載入延遲等意外狀況。
"""

from __future__ import annotations

import re
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import cv2
import numpy as np
import yaml

from . import dailystate, logger, vision
from .adb import Device
from .config import LOG_DIR, WEEKDAYS, resource_file
from .vision import Match, Region

log = logger.get("engine")


class ScriptError(RuntimeError):
    """腳本定義有誤。"""



def _option_reason(spec: str | list[str]) -> str:
    """把 when_option 寫成人看得懂的條件，用在「這條規則為何不啟用」的訊息。"""
    if isinstance(spec, list):
        return "、".join(_option_reason(s) for s in spec)
    if "=" in spec:
        key, _, val = spec.partition("=")
        return f"{key.strip()} = {val.strip()}"
    if spec.startswith("!"):
        return f"{spec[1:]} = false"
    return f"{spec} = true"


def _weekdays(value: Any, rule_name: str) -> list[int]:
    """把 when_weekday 轉成星期數字（0 是星期一）。⚠ 無法辨識的寫法在載入時就報錯。"""
    if value is None:
        return []
    days = []
    for item in [value] if isinstance(value, (str, int)) else value:
        day = WEEKDAYS.get(str(item).strip().lower().removeprefix("週")
                           .removeprefix("星期"))
        if day is None:
            raise ScriptError(f"規則「{rule_name}」的 when_weekday 認不得：{item}"
                              "（要寫成「週一」這種形式）")
        days.append(day)
    return days


def _state_label(rule_name: str) -> str:
    """取規則名稱「→」前面的部分當狀態標籤，例如「配對中」。"""
    return rule_name.split("→")[0].strip() or rule_name


def _xy(arg: Any, default: tuple[int, int] | None = None) -> tuple[int | None, int | None]:
    """從動作參數取出一組座標。`tap_match: []` 與 `tap_match:` 都表示沒有參數。"""
    if isinstance(arg, (list, tuple)) and len(arg) >= 2:
        return int(arg[0]), int(arg[1])
    return default if default is not None else (None, None)


@dataclass
class Rule:
    """一條規則：條件成立時執行一串動作。

    條件欄位之間是 AND：require 全部存在、measure 符合門檻、template 任一符合。
    template 和 absent 不能併用（有 template 時 absent 會被忽略）。
    """

    name: str
    template: list[str] = field(default_factory=list)   # 任一符合即觸發
    threshold: float | None = None
    region: tuple[int, int, int, int] | None = None     # 規則級，不能只套在單一模板
    absent: list[str] = field(default_factory=list)     # 全都找不到時才觸發
    # 前置條件：這些模板必須全部存在，一律全畫面搜尋，不受 region 限制。
    require: list[str] = field(default_factory=list)
    # 量顏色寬度的條件（順序條、血條），欄位見 measure_raw()。
    measure: dict[str, Any] | None = None
    # 找指定顏色的色塊，外框當比對結果（tap_match 點中心），欄位見 vision.find_blob()。
    # `absent: true` 表示那塊顏色不在。
    blob: dict[str, Any] | None = None
    # 有多個匹配時挑哪一個：best 分數最高（預設）、lowest / highest 最下 / 最上、
    # first / last 最左 / 最右，或直接給數字＝由左數來第幾個（1 起算）。
    pick: str | int = "best"
    # pick 是否跨模板比較。false 時 template 的順序就是優先度。
    pick_across: bool = False
    # 綁定 config 的 options 開關，前面加 ! 表示反向，也可以寫 key=value；
    # 給清單就是全部都要成立。
    when_option: str | list[str] | None = None
    # 只在星期幾成立（0 是星期一），寫法同 weekly_at。
    when_weekday: list[int] = field(default_factory=list)
    # 綁定 set_flag 設定的旗標，前面加 ! 表示反向；給清單時全部都要成立。
    when_flag: list[str] = field(default_factory=list)
    # 這幾條規則都用完（停用或達到 max_fires、max_fires_daily）才成立。
    when_spent: list[str] = field(default_factory=list)
    actions: list[dict[str, Any]] = field(default_factory=list)
    cooldown: float = 0.0                # 觸發後多久內不再觸發（秒）
    once: bool = False                   # 整場只觸發一次
    max_fires: int = 0                   # 最多觸發幾次，0 表示不限
    # 當日最多觸發幾次，跨執行保留（max_fires 每輪重置）。
    # ⚠ 只用在畫面上讀不到次數的情況，見 core/dailystate.py。
    max_fires_daily: int = 0
    # 條件持續成立這麼多秒才觸發。⚠ 後備規則一定要設，否則畫面轉場時會誤動作。
    sustain: float = 0.0

    _last_fired: float = field(default=0.0, repr=False)
    _fires: int = field(default=0, repr=False)
    _disabled: bool = field(default=False, repr=False)
    _since: float = field(default=0.0, repr=False)   # 條件從何時開始持續成立
    _today: int = field(default=0, repr=False)       # 今天已經觸發幾次
    _daily_key: str = field(default="", repr=False)  # 每日計數在狀態檔裡的鍵

    def ready(self, now: float) -> bool:
        if self._disabled:
            return False
        if self.once and self._fires:
            return False
        if self.max_fires and self._fires >= self.max_fires:
            return False
        if self.max_fires_daily and self._today >= self.max_fires_daily:
            return False
        return now - self._last_fired >= self.cooldown

    def spent(self) -> bool:
        """已經不會再觸發（不看 cooldown）。"""
        return (self._disabled
                or (self.once and self._fires > 0)
                or bool(self.max_fires and self._fires >= self.max_fires)
                or bool(self.max_fires_daily and self._today >= self.max_fires_daily))

    def mark_fired(self, now: float) -> None:
        self._last_fired = now
        self._fires += 1
        if self.max_fires_daily:
            self._today = dailystate.add(self._daily_key)


@dataclass
class Script:
    """一份腳本：規則表，加上結束程序與脫困門檻。"""

    name: str
    package: str | None
    rules: list[Rule]
    # 一輪結束後無條件執行的動作。⚠ 沒有條件保護畫面，只能用 tap_template。
    on_finish: list[dict[str, Any]] = field(default_factory=list)
    # 畫面靜止這麼多秒就按返回鍵脫困
    stuck_timeout: float = 90.0
    # 一輪最多幾分鐘，0 表示不限。用來終止規則互相觸發的循環（stuck_timeout 偵測不到）。
    # ⚠ 只給正常流程很短的腳本設，否則會中斷戰鬥。
    max_minutes: float = 0.0
    # 等待時附在狀態後面的即時資訊，格式同 log_match。
    status: dict[str, Any] = field(default_factory=dict)
    # 腳本檔名（不含副檔名），當 state.json 的鍵前綴，避免不同腳本的同名規則共用計數。
    stem: str = ""

    def referenced_templates(self) -> set[str]:
        """列出腳本用到的所有模板名稱，供 doctor 檢查是否齊全。"""
        names: set[str] = set()
        blocks = [r.actions for r in self.rules] + [self.on_finish]
        for rule in self.rules:
            names |= set(rule.template) | set(rule.absent) | set(rule.require)
        for actions in blocks:
            for action in actions:
                for verb, arg in action.items():
                    if verb in ("tap_template", "tap_all", "wait_for") and arg:
                        names |= {arg} if isinstance(arg, str) else set(arg)
                    elif verb == "log_match" and arg:
                        for spec in arg.values():
                            names |= set((spec.get("of") or {}).values())
        for spec in self.status.values():
            names |= set((spec.get("of") or {}).values())
        return names

    @classmethod
    def load(cls, name: str, options: dict[str, Any] | None = None) -> "Script":
        path = resource_file("scripts", f"{Path(name).stem}.yaml")
        if not path.is_file():
            raise ScriptError(f"找不到腳本：{path}")
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        # ⚠ 代入設定值要在建立 Rule 之前：sustain 等欄位建立時就會 float()。
        raw = resolve_vars(raw, options or {})

        def as_list(value) -> list[str]:
            if value is None:
                return []
            return [value] if isinstance(value, str) else list(value)

        rules = []
        for i, item in enumerate(raw.get("rules") or []):
            if "name" not in item:
                raise ScriptError(f"{path} 第 {i + 1} 條規則缺少 name")
            region = item.get("region")
            rules.append(
                Rule(
                    name=item["name"],
                    template=as_list(item.get("template")),
                    threshold=item.get("threshold"),
                    region=tuple(region) if region else None,
                    absent=as_list(item.get("absent")),
                    require=as_list(item.get("require")),
                    measure=item.get("measure"),
                    blob=item.get("blob"),
                    pick=item.get("pick", "best"),
                    pick_across=bool(item.get("pick_across", False)),
                    when_option=item.get("when_option"),
                    when_flag=as_list(item.get("when_flag")),
                    when_spent=as_list(item.get("when_spent")),
                    when_weekday=_weekdays(item.get("when_weekday"), item["name"]),
                    actions=item.get("do") or [],
                    cooldown=float(item.get("cooldown", 0)),
                    once=bool(item.get("once", False)),
                    max_fires=int(item.get("max_fires", 0)),
                    max_fires_daily=int(item.get("max_fires_daily", 0)),
                    sustain=_seconds(item, "sustain"),
                )
            )

        # 每日計數的鍵，帶腳本名前綴。
        for rule in rules:
            if rule.max_fires_daily:
                rule._daily_key = f"{Path(name).stem}/{rule.name}"
                rule._today = dailystate.get(rule._daily_key)

        # 載入時檢查 tally 的形狀。⚠ 不可與 max_fires_daily 並用：同一次觸發會計兩次。
        for rule in rules:
            for action in rule.actions:
                if "tally" not in action:
                    continue
                label = action["tally"]
                if not isinstance(label, str) or not label.strip():
                    raise ScriptError(f"規則「{rule.name}」的 tally 要給一個名稱")
                if rule.max_fires_daily:
                    raise ScriptError(
                        f"規則「{rule.name}」同時有 tally 與 max_fires_daily，"
                        "同一件事會被數兩次")

        # 載入時檢查 reset_fires 指的規則名稱。
        known = {r.name for r in rules}
        for rule in rules:
            missing = sorted(set(rule.when_spent) - known)
            if missing:
                raise ScriptError(
                    f"規則「{rule.name}」的 when_spent 指到不存在的規則："
                    + "、".join(missing))
            for action in rule.actions:
                target = action.get("reset_fires")
                if target is None:
                    continue
                wanted = {target} if isinstance(target, str) else set(target or [])
                missing = sorted(wanted - known)
                if missing:
                    raise ScriptError(
                        f"規則「{rule.name}」的 reset_fires 指到不存在的規則："
                        + "、".join(missing))

        # finish 只接受空值（跑結束程序）與 skip_cleanup（不跑）。
        for rule in rules:
            for action in rule.actions:
                if "finish" not in action:
                    continue
                arg = action["finish"]
                if arg not in (None, "", "skip_cleanup"):
                    raise ScriptError(
                        f"規則「{rule.name}」的 finish 參數只能留空或 skip_cleanup，"
                        f"目前是：{arg}")

        # 載入時檢查 when_flag 的名稱有對應的 set_flag。
        settable: set[str] = set()
        for rule in rules:
            for action in rule.actions:
                for verb in ("set_flag", "clear_flag"):
                    arg = action.get(verb)
                    if arg:
                        settable |= {arg} if isinstance(arg, str) else set(arg)
                top_up = action.get("top_up")
                if isinstance(top_up, dict) and top_up.get("flag"):
                    settable.add(top_up["flag"])
        for rule in rules:
            missing = sorted({f.lstrip("!") for f in rule.when_flag} - settable)
            if missing:
                raise ScriptError(
                    f"規則「{rule.name}」的 when_flag 指到沒有人會設定的旗標："
                    + "、".join(missing))

        return cls(
            name=raw.get("name", name),
            package=raw.get("package"),
            rules=rules,
            on_finish=raw.get("on_finish") or [],
            stuck_timeout=float(raw.get("stuck_timeout", 90)),
            max_minutes=float(raw.get("max_minutes", 0)),
            status=raw.get("status") or {},
            stem=Path(name).stem,
        )


def _seconds(item: dict[str, Any], key: str) -> float:
    """取秒數。`sustain: 300` 與 `sustain_minutes: 5` 等價。"""
    if item.get(key) is not None:
        return float(item[key])
    minutes = item.get(f"{key}_minutes")
    return float(minutes) * 60 if minutes is not None else 0.0


_VAR_RE = re.compile(r"^\$\{(\w+)(?::([^}]*))?\}$")


def resolve_vars(node: Any, options: dict[str, Any]) -> Any:
    """把腳本裡的 `${設定名}` / `${設定名:預設值}` 換成設定值。

        sustain: "${raid_join_sustain:20}"     設定檔沒填就用 20

    ⚠ 一定要帶預設值，否則舊的 config.yaml 會載入失敗。
    ⚠ 只處理整個字串就是一個變數的情況，才能保留數值型別。
    """
    if isinstance(node, dict):
        return {k: resolve_vars(v, options) for k, v in node.items()}
    if isinstance(node, list):
        return [resolve_vars(v, options) for v in node]
    if not isinstance(node, str):
        return node

    m = _VAR_RE.match(node.strip())
    if not m:
        return node
    key, default = m.group(1), m.group(2)
    value = options.get(key)
    if value is not None:
        return value
    if default is None:
        raise ScriptError(f"設定檔缺少「{key}」，而腳本沒有為它準備預設值")
    return yaml.safe_load(default)      # 讓 "20" 變成數字而不是字串


# `wait_for` 的等待上限（秒），用於跨過換頁與載入，不用於等待戰鬥。
WAIT_FOR_TIMEOUT = 25.0

# `top_up` 先把組數按「−」歸零，按這麼多下。遊戲的組數上限是 20。
TOP_UP_CLEAR = 25


def _as_index(pick: Any) -> int | None:
    """把 pick 讀成「由左數來第幾個」，不是數字就回傳 None。⚠ 排除 bool（True 是 int 的子類）。"""
    if isinstance(pick, bool):
        return None
    if isinstance(pick, int):
        return pick if pick >= 1 else None
    if isinstance(pick, str) and pick.strip().isdigit():
        return max(int(pick), 1)
    return None


# 順序條「單位數 ↔ 人數」的換算式，校準資料見 CLAUDE.md。⚠ 估計值，誤差約 ±2～3 人。
UNITS_PER_PLAYER = 2.25
UNITS_BASE = 5.75


def units_for_players(players: float) -> float:
    """人數換算成順序條單位數。"""
    return UNITS_PER_PLAYER * float(players) + UNITS_BASE


def players_for_units(units: float) -> float:
    """順序條單位數換算成人數。"""
    return (float(units) - UNITS_BASE) / UNITS_PER_PLAYER


def _threshold(spec: dict[str, Any], key: str) -> float | None:
    """取門檻值。`at_least` 是單位數，`at_least_players` 是人數（自動換算）。"""
    if spec.get(key) is not None:
        return float(spec[key])
    people = spec.get(f"{key}_players")
    return units_for_players(people) if people is not None else None


# 具名的挑選策略，單一模板與 pick_across 共用。`min()` 取最小，往畫面下方或右邊挑的取負值。
_PICK_KEYS = {
    "lowest": lambda m: -m.y,      # y 最大 = 畫面最下面
    "highest": lambda m: m.y,
    "last": lambda m: -m.x,
    "first": lambda m: m.x,
}


def measure_raw(screen: np.ndarray, spec: dict[str, Any]) -> float:
    """量出 `measure` 的原始數值（還沒平滑、還沒比門檻）。

    欄位：
        region    [x, y, w, h]　要量的區域，必填
        metric    span（預設）量顏色寬度　units 估順序條上排了幾個單位
        color     [B, G, R]　　要量的顏色，必填
        hue       units 用：圖示外圈的色相範圍，預設 [94, 106]
        tol       容許誤差，預設 22（畫面有壓縮雜訊，不能要求完全相等）
        fill      一欄要有多少比例接近該色才算命中，預設 0.6

    ⚠ 放在模組層級，explain 與實際執行共用同一套判斷。
    """
    region = tuple(spec["region"])
    color = tuple(spec["color"])
    tol = int(spec.get("tol", 22))
    fill = float(spec.get("fill", 0.6))

    if spec.get("metric", "span") == "units":
        return vision.queue_units(
            screen, region, color, tuple(spec.get("hue", (94, 106))), tol, fill)
    return float(vision.color_span(screen, region, color, tol, fill))


def measure_ok(value: float, spec: dict[str, Any]) -> bool:
    """數值符不符合 `at_most` / `at_least` 門檻。"""
    ok = True
    most = _threshold(spec, "at_most")
    least = _threshold(spec, "at_least")
    if most is not None:
        ok = ok and value <= most
    if least is not None:
        ok = ok and value >= least
    return ok


def _measure_unit(spec: dict[str, Any]) -> str:
    return "個" if spec.get("metric") == "units" else "px"


def _measure_text(value: float, spec: dict[str, Any]) -> str:
    """數值加上單位。units 留一位小數；門檻以人數設定時一併寫出換算人數。

    ⚠ 只在 `*_players` 門檻換算：換算式只對公會討伐的順序條校準過。
    """
    if spec.get("metric") != "units":
        return f"{value:.0f} px"
    text = f"約 {value:.1f} 個單位"
    if spec.get("at_least_players") is None and spec.get("at_most_players") is None:
        return text
    return f"{text}／約 {max(0.0, players_for_units(value)):.1f} 人"


def describe_measure(spec: dict[str, Any]) -> str:
    """把 measure 的門檻寫成一句話，給 explain 與紀錄用。"""
    parts = []
    least, most = _threshold(spec, "at_least"), _threshold(spec, "at_most")
    if least is not None:
        parts.append(f"≥{least:g}")
    if most is not None:
        parts.append(f"≤{most:g}")
    if not parts:
        return "無門檻"
    text = "、".join(parts) + " " + _measure_unit(spec)
    people = spec.get("at_least_players") or spec.get("at_most_players")
    return f"{text}／約 {people:g} 人" if people is not None else text


def _measure_trace(raw: float, filled: int, window: int, spec: dict[str, Any]) -> str:
    """平滑讀數的診斷字串：單幀讀數與平滑視窗的填充度。"""
    if window <= 1:
        return ""
    unit = _measure_unit(spec)
    return f"單幀 {raw:.1f} {unit}、視窗 {filled}/{window}；"


def apply_options(rules: list[Rule], options: dict[str, Any]) -> list[Rule]:
    """依 config 的開關停用不適用的規則，回傳被停用的那些。

    `when_option` 支援這幾種寫法，給清單就是全部都要成立：
        like_teammates          該開關為 true 才啟用（設定檔沒有這個鍵也算 true）
        !claim_reward           該開關為 false 才啟用
        buy_counts=2            該設定值等於 2 才啟用
        buy_arena_tickets=true  同上，用於布林

    ⚠ 會花費資源的規則一定要用 `=` 寫法：設定檔缺鍵時不啟用。正向寫法缺鍵時預設成立。
    """
    disabled = []
    for rule in rules:
        specs = rule.when_option
        if not specs:
            continue
        if not all(_option_ok(spec, options)
                   for spec in ([specs] if isinstance(specs, str) else specs)):
            rule._disabled = True
            disabled.append(rule)
    return disabled


def _option_ok(spec: str, options: dict[str, Any]) -> bool:
    """單一個 when_option 條件成不成立，寫法見 apply_options。"""
    if "=" in spec:
        # 值比較，沒設定這個項目就不成立。
        # ⚠ 忽略大小寫：YAML 的 true 經 str() 是 "True"。
        key, _, want_value = spec.partition("=")
        actual = options.get(key.strip())
        return (actual is not None
                and str(actual).strip().lower() == want_value.strip().lower())
    key, want = spec, True
    if key.startswith("!"):
        key, want = key[1:], False
    return bool(options.get(key, True)) == want


class Engine:
    """執行腳本的主迴圈。"""

    def __init__(
        self, device: Device, script: Script, repeat: int = 0, dry_run: bool = False,
        stop_event: threading.Event | None = None,
        status_hook: Callable[[str], None] | None = None,
    ):
        self.device = device
        self.script = script
        self.repeat = repeat            # 0 表示不限次數
        self.dry_run = dry_run          # 只判斷不操作，用來驗證規則
        self.completed = 0
        self.cfg = device.cfg
        # 兩層停止旗標：_stop 是這一輪結束，stop_event 是外部要求整個程式結束。
        # 分開才不會在 reset() 時清掉使用者的停止要求。
        self.yielded = False        # 上一輪是讓出執行權，而不是腳本自己結束
        self._stop = False
        self._stop_event = stop_event or threading.Event()
        self._finishing = False         # 正在跑 on_finish，此時等待不可被打斷
        self._skip_cleanup = False      # `finish: skip_cleanup` 要求跳過 on_finish
        # 等待狀態的回報掛鉤，介面用來更新狀態列。
        self._status_hook = status_hook
        self._last_change = time.time()
        self._prev_frame: np.ndarray | None = None
        self._until: datetime | None = None      # 到這個時刻就讓出執行權給下一個腳本
        self._yielded_now = False                # yield_if_due 剛讓出執行權，_execute 要中斷
        self._waiting_name: str | None = None
        self._waiting_block_start = 0.0  # 這一整段「沒有動作」是何時開始的
        self._waiting_logged = 0.0       # 上次寫心跳到紀錄檔的時間
        self._measure_logged: dict[str, float] = {}   # 各 measure 上次寫紀錄的時間
        # 各 measure 最近幾次的讀數，給 smooth 取中位數用
        self._measure_history: dict[str, deque[float]] = {}
        # 只有終端機才用 \r 原地更新；輸出導向檔案或管線時改為節流寫紀錄。
        self._tty = bool(getattr(sys.stdout, "isatty", lambda: False)())
        self._options_logged = False     # 「略過規則」只寫第一輪
        self._last_log_text = ""         # log_text 讀到一樣的就不重寫
        # 這一輪已成立的旗標（set_flag）。
        self._flags: set[str] = set()
        # 色塊規則要跳過的位置 [(到期時刻, x, y)]，見 avoid_last_blob；以及上一次
        # tap_match 點到的色塊中心。
        self._blob_avoid: list[tuple[float, int, int]] = []
        self._last_blob_tap: tuple[int, int] | None = None
        self._apply_options(self.cfg.options)

    def _apply_options(self, options: dict[str, bool]) -> None:
        """依 config 的開關停用不適用的規則。⚠ 只在第一輪寫紀錄。"""
        disabled = apply_options(self.script.rules, options)
        if self._options_logged:
            return
        self._options_logged = True
        # 同一個開關停用的規則合成一行，關掉一整段功能時才不會連印十幾行。
        groups: dict[str, list[str]] = {}
        for rule in disabled:
            groups.setdefault(_option_reason(rule.when_option), []).append(rule.name)
        for reason, names in groups.items():
            if len(names) == 1:
                log.info("略過規則「%s」（需要設定 %s）", names[0], reason)
            else:
                log.info("略過 %d 條規則（需要設定 %s）：「%s」等", len(names), reason,
                         names[0])

    def reset(self) -> None:
        """重置執行狀態，讓同一個引擎可以再跑一輪（每日排程用）。"""
        self.completed = 0
        self._stop = False
        self.yielded = False
        self._last_change = time.time()
        self._prev_frame = None
        self._waiting_name = None
        self._waiting_block_start = 0.0
        self._measure_logged.clear()
        self._measure_history.clear()
        self._last_log_text = ""
        self._skip_cleanup = False
        # 用指派而非 clear()：測試以 Engine.__new__ 建立的引擎沒有這個欄位。
        self._flags = set()
        self._blob_avoid = []
        self._last_blob_tap = None
        for rule in self.script.rules:
            rule._fires = 0
            rule._last_fired = 0.0
            rule._disabled = False
            # ⚠ 每日上限不歸零，從狀態檔取回今天已觸發的次數。
            if rule.max_fires_daily:
                rule._today = dailystate.get(rule._daily_key)
        self._apply_options(self.cfg.options)

    # ---------- 主迴圈 ----------

    def run(self, until: datetime | None = None) -> int:
        """執行到這一輪結束。`until` 是下一個排程時刻，到了就讓出執行權。

        ⚠ 讓出執行權的檢查點是 `count` 與 `yield_if_due` 動作，不是每一輪，避免中斷戰鬥。
          不經過 `count` 的路徑（副本「未達 S → 退出重打」）要在開始下一場之前放 `yield_if_due`。
        """
        self._until = until
        if self.script.package:
            self._ensure_app()

        started = time.time()
        try:
            while not self._stop and not self._stop_event.is_set():
                if self.repeat and self.completed >= self.repeat:
                    log.info("已完成目標次數 %d 次", self.completed)
                    break

                over = self.script.max_minutes * 60
                if over and time.time() - started > over:
                    log.warning("已執行 %.0f 分鐘仍未結束，執行結束程序並讓出執行權給下一個腳本",
                                self.script.max_minutes)
                    break

                round_started = time.time()
                screen = self.device.screencap()
                self._track_stuck(screen)

                hit = self._match_rule(screen)
                if hit:
                    rule, match = hit
                    rule.mark_fired(time.time())
                    if rule.actions:
                        self._end_waiting_line()   # 要輸出別的訊息了，先收掉進度行
                        log.info("觸發規則：%s", rule.name)
                        self._emit_status(rule.name)
                        self._execute(rule.actions, screen, match)
                    else:
                        # 沒有動作的規則是純攔截，規則名稱「→」前面那段當等待訊息。
                        self._log_waiting(_state_label(rule.name), screen)
                else:
                    # 沒有規則成立：通常是轉場或載入中的短暫空檔。
                    self._log_waiting("等待畫面變化", screen)

                # ⚠ tick 是每輪之間的最短間隔，不是每輪額外的等待。
                self._sleep(max(0.0, self.cfg.runtime.tick
                                - (time.time() - round_started)))
        except KeyboardInterrupt:
            self._end_waiting_line()
            log.info("使用者中斷")
        else:
            self._end_waiting_line()
            self._run_on_finish()

        self._end_waiting_line()
        elapsed = time.time() - started
        log.info("結束：完成 %d 次，耗時 %s", self.completed,
                 logger.pretty_seconds(elapsed))
        return self.completed

    def stop(self) -> None:
        self._stop = True

    def abort(self) -> None:
        """使用者中斷這一輪：立刻結束，不跑結束程序。"""
        self._skip_cleanup = True
        self._stop = True

    def _sleep(self, seconds: float) -> bool:
        """可被中斷的等待，回傳是否被要求停止。

        ⚠ 結束程序期間不可中斷：那些等待是給換頁動畫的，否則會把上一頁的座標點在新頁上。
        """
        if self._finishing:
            time.sleep(seconds)
            return False
        return self._stop_event.wait(seconds)

    def _run_on_finish(self) -> None:
        """執行結束程序（例如回到家園），並把進度回報給狀態列。"""
        if not self.script.on_finish or self.dry_run or self._skip_cleanup:
            return
        self._finishing = True
        try:
            screen = self.device.screencap()
            steps = self.script.on_finish
            for i, action in enumerate(steps, 1):
                self._emit_status(f"結束程序執行中　第 {i} 步，共 {len(steps)} 步")
                self._execute([action], screen, None)
        except Exception as e:                      # 結束程序失敗不該影響主要結果
            log.warning("結束程序未完成：%s", e)
        finally:
            self._finishing = False

    # ---------- 內部 ----------

    def _ensure_app(self) -> None:
        pkg = self.script.package
        if not self.device.is_app_running(pkg):
            log.info("遊戲未執行，正在啟動 ...")
            self.device.launch_app(pkg)
            self._sleep(8)

    def _status_extra(self, screen: np.ndarray | None) -> str:
        """等待時附在狀態後面的即時資訊，例如「評級 A」。認不出來就不顯示。"""
        if screen is None or not self.script.status:
            return ""
        parts = []
        for label, spec in self.script.status.items():
            region = spec.get("region")
            limit = float(spec.get("threshold", self.cfg.runtime.threshold))
            best, best_score = "", 0.0
            for shown, template in (spec.get("of") or {}).items():
                got = vision.score(screen, template, region=region)
                if got > best_score:
                    best, best_score = shown, got
            if best_score >= limit:
                parts.append(f"{label} {best}")
        return "　".join(parts)

    def _log_waiting(self, name: str, screen: np.ndarray | None = None,
                     heartbeat: float = 300.0) -> None:
        """回報等待狀態：終端機原地更新同一行；紀錄檔只留心跳與離開等待時的總結。

        輸出導向檔案或管線時沒有原地更新，心跳間隔自動縮短。

        ⚠ 狀態切換不寫紀錄檔，避免戰鬥與載入的交替刷滿紀錄。
        ⚠ 經過時間算整段等待，切換狀態時不歸零。
        """
        now = time.time()
        if self._waiting_block_start == 0.0:    # 這一整段等待的起點
            self._waiting_block_start = now
            self._waiting_logged = now
        self._waiting_name = name

        elapsed = logger.pretty_seconds(now - self._waiting_block_start)
        if not self._tty and heartbeat > 60:
            heartbeat = 60.0

        if now - self._waiting_logged >= heartbeat:
            self._waiting_logged = now
            # ⚠ 先清掉原地更新的那一行。不可用 _end_waiting_line：它會把累計歸零。
            self._clear_waiting_line()
            log.info("等待中　%s（目前狀態：%s）", elapsed, name)

        # 即時資訊只附在狀態列與進度行，不進紀錄檔。
        extra = self._status_extra(screen)
        shown = f"{name}　{extra}" if extra else name
        if self._tty:
            self._draw_waiting_line(logger.transient("engine", f"{shown}　{elapsed}"))
        self._emit_status(f"{shown}　{elapsed}")

    def _emit_status(self, text: str) -> None:
        """把目前狀態送給外部觀察者（介面狀態列）。掛鉤的例外一律吞掉，不影響執行。"""
        if self._status_hook is None:
            return
        try:
            self._status_hook(text)
        except Exception:
            pass

    def _draw_waiting_line(self, line: str) -> None:
        """在同一行原地更新等待訊息，用 ANSI 的「清除到行尾」。"""
        if logger.ansi_ready():
            print(f"\r{line}\x1b[K", end="", flush=True)
        else:
            print(f"\r{line}    ", end="", flush=True)

    def _clear_waiting_line(self) -> None:
        """只把原地更新的那一行擦掉，不動累計狀態。"""
        if not self._tty:
            return
        if logger.ansi_ready():
            print("\r\x1b[K", end="", flush=True)
        else:
            print("\r" + " " * 90 + "\r", end="", flush=True)

    def _end_waiting_line(self) -> None:
        """結束原地更新的那一行，等超過 60 秒才留一筆總結。⚠ 要在輸出其他訊息之前呼叫。"""
        if self._waiting_block_start == 0.0:
            return
        total = time.time() - self._waiting_block_start
        self._clear_waiting_line()
        if total >= 60:
            log.info("等待結束，共 %s（最後狀態：%s）",
                     logger.pretty_seconds(total), self._waiting_name)
        self._waiting_name = None
        self._waiting_block_start = 0.0

    def _threshold_of(self, rule: Rule) -> float:
        return (rule.threshold if rule.threshold is not None
                else self.cfg.runtime.threshold)

    def _condition(
        self, screen: np.ndarray, rule: Rule, th: float
    ) -> tuple[bool, Match | None]:
        """判斷規則的條件是否成立，回傳（是否成立, 比對結果）。"""
        # 旗標排在最前面：不成立時 sustain 不累加。
        # ⚠ selftest 的引擎（Engine.__new__）沒有 _flags，旗標、星期與 when_spent 一律視為成立。
        flags = getattr(self, "_flags", None)
        if (rule.when_weekday and flags is not None
                and datetime.now().weekday() not in rule.when_weekday):
            return False, None
        if rule.when_flag and flags is not None:
            for want in rule.when_flag:
                if (want[1:] in flags) if want.startswith("!") else (want not in flags):
                    return False, None
        if rule.when_spent and flags is not None:
            if any(not r.spent() for r in self.script.rules if r.name in rule.when_spent):
                return False, None

        if rule.require and not all(
            self._find(screen, name, th) for name in rule.require
        ):
            return False, None

        if rule.measure and not self._measure(screen, rule):
            return False, None

        found = None
        if rule.blob:
            now = time.time()
            avoid = [(x, y) for until, x, y in getattr(self, "_blob_avoid", ())
                     if until > now]
            found = vision.find_blob(screen, rule.blob, avoid)
            if bool(found) == bool(rule.blob.get("absent")):
                return False, None

        if rule.template:
            if rule.pick_across and len(rule.template) > 1:
                # 每個模板各自挑出的贏家再比一次，結果等於全域的極值。
                pool = [m for m in (self._locate(screen, n, th, rule)
                                    for n in rule.template) if m]
                if not pool:
                    return False, None
                key = _PICK_KEYS.get(rule.pick)
                return True, (min(pool, key=key) if key
                              else max(pool, key=lambda m: m.score))
            for name in rule.template:
                m = self._locate(screen, name, th, rule)
                if m:
                    return True, m
            return False, None

        if rule.absent:
            hit = any(
                self._find(screen, name, th, rule.region) for name in rule.absent
            )
            return (not hit), None

        if rule.require or rule.measure or rule.blob:
            # 沒有 template 與 absent：前置條件與量測都成立就成立；色塊外框當比對結果。
            return True, found

        return False, None

    def _measure(self, screen: np.ndarray, rule: Rule) -> bool:
        """評估 measure 條件，每 30 秒把數值寫進紀錄。`smooth: N` 取最近 N 次的中位數。

        ⚠ 每輪只取樣一次（結果快取在 _measure_frame）：_match_rule 會掃兩遍規則。
        """
        cache = getattr(self, "_measure_frame", None)
        if cache is not None and rule.name in cache:
            return cache[rule.name]

        raw = measure_raw(screen, rule.measure)
        value, filled = raw, 0
        window = int(rule.measure.get("smooth", 0))
        history = getattr(self, "_measure_history", None)
        if window > 1 and history is not None:
            samples = history.setdefault(rule.name, deque(maxlen=window))
            samples.append(raw)
            filled = len(samples)
            value = float(np.median(samples))

        ok = measure_ok(value, rule.measure)
        if cache is not None:
            cache[rule.name] = ok

        label = rule.measure.get("log")
        # selftest 的引擎沒有紀錄欄位：照算，不寫紀錄。
        seen = getattr(self, "_measure_logged", None)
        if label and seen is not None:
            now = time.time()
            if now - seen.get(rule.name, 0.0) >= 30:
                first = rule.name not in seen
                seen[rule.name] = now
                self._end_waiting_line()
                # ⚠ 門檻只在第一筆寫。單幀讀數與視窗填充度用來分辨「量錯」與「還在追畫面」。
                spec = rule.measure
                people = spec.get("at_least_players", spec.get("at_most_players"))
                if people is not None:
                    # 門檻以人數設定時，人數放最前面，單位數與平滑資料放後面。
                    detail = f"量測：{value:.1f} 個單位"
                    if window > 1:
                        detail += f"，單幀 {raw:.1f}、樣本 {filled}/{window}"
                    result = "已達到" if ok else "未達到"
                    head = f"{label}估計約 {max(0.0, players_for_units(value)):.1f} 人"
                    if first:
                        log.info("%s（門檻 %g 人，%s）　%s", head, float(people), result, detail)
                    else:
                        log.info("%s（%s）　%s", head, result, detail)
                else:
                    trace = _measure_trace(raw, filled, window, spec)
                    if first:
                        log.info("%s：%s（%s門檻 %s，%s）", label,
                                 _measure_text(value, spec), trace,
                                 describe_measure(spec), "符合" if ok else "不符合")
                    else:
                        log.info("%s：%s（%s%s）", label,
                                 _measure_text(value, spec), trace,
                                 "符合" if ok else "不符合")
        return ok

    def _match_rule(self, screen: np.ndarray) -> tuple[Rule, Match | None] | None:
        """回傳第一條成立的規則，以及它的比對結果（若有）。"""
        # 同一張畫面的量測與比對都只算一次（下面會掃兩遍規則）
        self._measure_frame: dict[str, bool] = {}
        self._match_frame: dict[tuple, Any] = {}
        now = time.time()

        # ⚠ 有 sustain 的規則要先全部評估一次，畫面離開時計時才會歸零。
        for rule in self.script.rules:
            if not rule.sustain or rule._disabled:
                continue
            try:
                ok, _ = self._condition(screen, rule, self._threshold_of(rule))
            except FileNotFoundError as e:
                rule._disabled = True
                log.warning("停用規則「%s」：%s", rule.name, e)
                continue
            rule._since = (rule._since or now) if ok else 0.0

        for rule in self.script.rules:
            if not rule.ready(now):
                continue
            try:
                ok, m = self._condition(screen, rule, self._threshold_of(rule))
            except FileNotFoundError as e:
                # 模板還沒製作：停用這條規則，讓其餘流程照常運作
                rule._disabled = True
                log.warning("停用規則「%s」：%s", rule.name, e)
                continue

            if not ok:
                continue
            if rule.sustain and now - rule._since < rule.sustain:
                continue        # 還沒持續夠久，讓後面的規則有機會
            return rule, m
        return None

    def _find(
        self, screen: np.ndarray, name: str, threshold: float,
        region: Region | None = None,
    ) -> Match | None:
        """有快取的 vision.find，同一輪裡同一組參數只比對一次。

        全畫面彩色比對一次 85～125ms；raid 一輪 64 次比對只有 21 種不重複。

        ⚠ 快取在 _match_rule 開頭重置。動作裡的 tap_template 不走快取。
        """
        cache = getattr(self, "_match_frame", None)
        key = ("find", name, threshold, tuple(region) if region else None)
        if cache is not None and key in cache:
            return cache[key]
        got = vision.find(screen, name, threshold, region)
        if cache is not None:
            cache[key] = got
        return got

    def _find_all(
        self, screen: np.ndarray, name: str, threshold: float,
        region: Region | None = None,
    ) -> list[Match]:
        """有快取的 vision.find_all，說明同 _find。"""
        cache = getattr(self, "_match_frame", None)
        key = ("all", name, threshold, tuple(region) if region else None)
        if cache is not None and key in cache:
            return cache[key]
        got = vision.find_all(screen, name, threshold, region)
        if cache is not None:
            cache[key] = got
        return got

    def _locate(
        self, screen: np.ndarray, name: str, threshold: float, rule: Rule
    ) -> Match | None:
        """依規則的 pick 策略挑出一個匹配。"""
        if rule.pick == "best":
            return self._find(screen, name, threshold, rule.region)

        found = self._find_all(screen, name, threshold, rule.region)
        if not found:
            return None

        # 數字＝由左數來第幾個（1 起算）。⚠ 超出範圍時取最靠近的一端，避免規則不成立。
        nth = _as_index(rule.pick)
        if nth is not None:
            ordered = sorted(found, key=lambda m: m.x)
            return ordered[min(nth, len(ordered)) - 1]

        key = _PICK_KEYS.get(rule.pick)
        if key is None:
            log.warning("規則「%s」的 pick 值無效：%s，改用 best", rule.name, rule.pick)
            return max(found, key=lambda m: m.score)
        return min(found, key=key)

    def _track_stuck(self, screen: np.ndarray) -> None:
        """畫面長時間毫無變化時，按返回鍵嘗試脫困。"""
        if self._prev_frame is not None and self._prev_frame.shape == screen.shape:
            diff = float(np.mean(cv2.absdiff(self._prev_frame, screen)))
            if diff > 1.0:
                self._last_change = time.time()
        else:
            self._last_change = time.time()
        self._prev_frame = screen

        if time.time() - self._last_change > self.script.stuck_timeout:
            log.warning("畫面已靜止 %.0f 秒，按返回鍵嘗試脫困",
                        self.script.stuck_timeout)
            self.device.back()
            self._last_change = time.time()

    def _yield_if_due(self) -> bool:
        """排定時刻到了就讓出執行權（回傳 True），沒到什麼都不做。"""
        if not (self._until and datetime.now() >= self._until):
            return False
        log.info("已到下一個排程時刻，先結束這一輪並讓出執行權")
        self._stop = True
        # ⚠ yielded 用來區分讓出執行權與腳本自己結束：前者還有工作沒做，排程要排回去。
        self.yielded = True
        return True

    def _execute(
        self, actions: list[dict[str, Any]], screen: np.ndarray, match: Match | None
    ) -> None:
        for action in actions:
            for verb, arg in action.items():
                if self.dry_run and verb not in ("log", "screenshot", "wait", "count", "yield_if_due"):
                    log.info("[試跑] 略過動作 %s: %s", verb, arg)
                    continue
                self._do(verb, arg, screen, match)
                if self._yielded_now:
                    # yield_if_due 讓出執行權了：這條規則剩下的動作（多半是按配對）不做
                    self._yielded_now = False
                    return

    def _do(self, verb: str, arg: Any, screen: np.ndarray, match: Match | None) -> None:
        d = self.device

        if verb == "tap_match":
            if match:
                # 寫成 `tap_match: []` 或 `tap_match:` 都表示不偏移
                dx, dy = _xy(arg, default=(0, 0))
                cx, cy = match.center
                d.tap(cx + dx, cy + dy)
                if match.name == "blob":
                    self._last_blob_tap = (cx, cy)
            else:
                log.warning("tap_match 沒有可用的比對結果")

        elif verb == "tap":
            # 第三個數字是連點幾次（加減鈕那種），可以寫 ${設定:預設}；0 就是不點。
            x, y = _xy(arg)
            if x is None:
                log.warning("tap 需要 [x, y] 兩個座標，收到：%s", arg)
            else:
                if len(arg) >= 3:
                    d.tap_repeat(x, y, int(arg[2]))
                else:
                    d.tap(x, y)

        elif verb == "tap_template":
            # ⚠ 重新抓畫面：tap_template 前面常有 wait 或點擊，畫面已經換了。
            screen = d.screencap()
            names = [arg] if isinstance(arg, str) else list(arg)
            for name in names:
                try:
                    m = vision.find(screen, name, self.cfg.runtime.threshold)
                except FileNotFoundError as e:
                    log.warning("%s", e)
                    continue
                if m:
                    d.tap(*m.center)
                    break
            else:
                log.warning("畫面上找不到任何模板：%s", names)

        elif verb == "tap_all":
            # 點擊畫面上所有符合的目標，同樣重新抓畫面。
            screen = d.screencap()
            names = [arg] if isinstance(arg, str) else list(arg)
            hits = 0
            for name in names:
                try:
                    found = vision.find_all(screen, name, self.cfg.runtime.threshold)
                except FileNotFoundError as e:
                    log.warning("%s", e)
                    continue
                for m in found:
                    d.tap(*m.center)
                    hits += 1
            log.info("點擊畫面上 %d 個目標", hits)

        elif verb == "swipe":
            x1, y1, x2, y2 = (int(v) for v in arg[:4])
            dur = int(arg[4]) if len(arg) > 4 else 300
            d.swipe(x1, y1, x2, y2, dur)
            # 鏡頭移動後座標全部錯開，avoid_last_blob 的記錄失效。
            self._blob_avoid = []

        elif verb == "avoid_last_blob":
            # 上一次 tap_match 點的色塊在這段時間（秒，預設 60）內不算。
            if self._last_blob_tap is not None:
                x, y = self._last_blob_tap
                self._blob_avoid.append((time.time() + float(arg or 60), x, y))
                self._last_blob_tap = None

        elif verb == "back":
            d.back()

        elif verb == "wait":
            self._sleep(float(arg))

        elif verb == "restart_app":
            # 最後手段：關閉遊戲再啟動，回到「開機 → 家園」這條路。
            # ⚠ 只掛在後備規則鏈的最後一條，前一條要先用完 max_fires：重新啟動要 152 秒。
            pkg = self.script.package
            if not pkg:
                log.warning("腳本沒有指定 package，無法重新啟動遊戲")
            else:
                # ⚠ 訊息保持中性：重新啟動的原因由觸發規則的名稱說明。
                log.warning("重新啟動遊戲")
                d.stop_app(pkg)
                self._sleep(3)
                d.launch_app(pkg)
                # ⚠ 前 35 秒全黑，後備規則的條件在黑畫面上一直成立，等待要超過這段。
                self._sleep(float(arg) if arg else 45)
                # ⚠ 畫面是這個動作換掉的，sustain 的計時全部歸零。
                for rule in self.script.rules:
                    rule._since = 0.0
                self._last_change = time.time()

        elif verb == "wait_for":
            # 等到畫面上出現其中一個模板才往下，最多 WAIT_FOR_TIMEOUT 秒，逾時直接往下走。
            # 用於 on_finish 這類無條件清單跨過換頁與載入。
            names = [arg] if isinstance(arg, str) else list(arg or [])
            deadline = time.time() + WAIT_FOR_TIMEOUT
            while time.time() < deadline:
                shot = d.screencap()
                if any(vision.exists(shot, n, self.cfg.runtime.threshold)
                       for n in names):
                    break
                if self._sleep(0.5):
                    break
            else:
                log.warning("等了 %.0f 秒仍沒看到：%s",
                            WAIT_FOR_TIMEOUT, "、".join(names))

        elif verb == "tally":
            # 當日計數，只數不擋，名稱由腳本給（多條規則可以數進同一格）。
            # ⚠ 不要用來決定「今天做過就跳過」，判斷要看畫面。
            dailystate.add(f"{self.script.stem}/{arg}")

        elif verb == "count":
            self.completed += 1
            log.info("完成第 %d 次", self.completed)
            # 一場結束是安全的讓出執行權時機（見 run）
            self._yield_if_due()

        elif verb == "yield_if_due":
            # 腳本標記的安全位置（見 run）。讓出執行權時由 _execute 中斷這條規則剩下的動作。
            self._yielded_now = self._yield_if_due()

        elif verb == "screenshot":
            # ⚠ 檔名要帶日期，否則跨天會互相覆蓋。
            name = arg if isinstance(arg, str) else datetime.now().strftime("%m%d-%H%M%S")
            path = LOG_DIR / "frames" / f"{name}.png"
            vision.imwrite_unicode(path, screen)
            log.info("已存截圖：%s", path)

        elif verb == "log_text":
            # 用系統內建 OCR 讀畫面文字寫進紀錄，不影響判斷，讀不到就寫「讀不到」。
            #
            # 寫法（每個欄位可以只給 region，或給 dict 帶參數）：
            #   log_text:
            #     選擇副本: {region: [110, 174, 510, 64], binary: 210, scale: 3}
            #     難度: {region: [30, 798, 170, 34], scale: 4, strip: 副本獎勵}
            #
            # `match` 是正規表示式，只取第一段符合的文字（去掉空白），對不上算讀不到。
            # ⚠ 讀出來和上一次相同就不重寫。
            from core import ocr

            screen = d.screencap()
            parts = []
            for label, spec in (arg or {}).items():
                spec = {"region": spec} if isinstance(spec, list) else dict(spec)
                strip = spec.pop("strip", None)
                pattern = spec.pop("match", None)
                text = ocr.read(screen, **spec)
                for junk in ([strip] if isinstance(strip, str) else (strip or [])):
                    text = text.replace(junk, "")
                if pattern:
                    found = re.search(pattern, text)
                    text = re.sub(r"\s+", "", found.group(0)) if found else ""
                parts.append(f"{label}：{text.strip() or '（讀不到）'}")
            line = "　".join(parts)
            if line != self._last_log_text:
                self._last_log_text = line
                log.info("%s", line)

        elif verb == "top_up":
            # 讀出今天已買幾組，把加減鈕調成「設定 − 已買」：先按「−」歸零，再按「+」補差額。
            #
            # 寫法：
            #   top_up:
            #     label: 鐵鎚
            #     read: [466, 404, 132, 24]    「今日限購：N/20」那一行
            #     minus: [472, 445]
            #     plus: [593, 445]
            #     target: "${material_hammer_sets:2}"
            #     flag: 素材有要買的          真的要買時設這個旗標
            #
            # ⚠ 讀不到就歸零、這一列不買。OCR 只取冒號與斜線之間的數字，倍率 3 八列全對，
            #   倍率 4 會多讀一個「1」（2/201）。
            from core import ocr

            spec = dict(arg or {})
            label = spec.get("label", "")
            text = ocr.read(d.screencap(), tuple(spec["read"]), scale=3)
            d.tap_repeat(*spec["minus"], TOP_UP_CLEAR)
            m = re.search(r"[:：]\s*(\d{1,2})\s*/", text)
            if not m:
                log.warning("%s：讀不到今天已經買了幾組（讀到「%s」），這一列不買",
                            label, text or "")
                return
            done, target = int(m.group(1)), int(spec["target"])
            need = max(0, target - done)
            if need:
                d.tap_repeat(*spec["plus"], need)
                if spec.get("flag"):
                    self._flags.add(spec["flag"])
            log.info("%s：今天已買 %d 組，設定 %d 組，%s", label, done, target,
                     f"這次買 {need} 組" if need else "不必再買")

        elif verb == "log_match":
            # 把畫面上比對到的項目寫進紀錄：給「顯示文字 → 模板」，取分數最高且過門檻者。
            # 只影響紀錄，認不出就寫「認不出」。
            #
            # 寫法：
            #   log_match:
            #     評級: {region: [270, 140, 200, 220],
            #            of: {S: rank_s, A: rank_a, B: rank_b}}
            #
            # ⚠ region 要給，單一字母不框住會誤中畫面別處的深色圖形。
            screen = d.screencap()
            parts = []
            for label, spec in (arg or {}).items():
                region = spec.get("region")
                limit = float(spec.get("threshold", self.cfg.runtime.threshold))
                best, best_score = "", 0.0
                for shown, template in (spec.get("of") or {}).items():
                    got = vision.score(screen, template, region=region)
                    if got > best_score:
                        best, best_score = shown, got
                parts.append(f"{label}："
                             f"{best if best_score >= limit else '（認不出）'}")
            log.info("%s", "　".join(parts))

        elif verb == "log":
            # 規則名稱之外的補充訊息，不加前綴。只在規則名稱沒說完時才寫。
            log.info("%s", arg)

        elif verb == "reset_fires":
            # 把指定規則的 max_fires 計數歸零，讓它可以再觸發。名稱在載入時檢查。
            names = {arg} if isinstance(arg, str) else set(arg or [])
            for r in self.script.rules:
                if r.name in names:
                    r._fires = 0

        elif verb == "set_flag" or verb == "clear_flag":
            # 設定或清除旗標，供後面的畫面判斷（when_flag）。名稱在載入時檢查。
            names = {arg} if isinstance(arg, str) else set(arg or [])
            if verb == "set_flag":
                self._flags |= names
            else:
                self._flags -= names

        elif verb == "finish":
            # 不寫紀錄：規則名稱已說明結束原因。
            # `finish: skip_cleanup` 跳過結束程序，用於遊戲進不去的情況（伺服器維護中）。
            if arg == "skip_cleanup":
                self._skip_cleanup = True
            self.stop()

        else:
            log.warning("未知的動作：%s", verb)
