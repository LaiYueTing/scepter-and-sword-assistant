"""腳本引擎：以 YAML 規則驅動的畫面狀態機。

運作方式是「看到什麼就做什麼」，而不是寫死一串固定操作：
每一輪抓一張畫面，由上而下檢查規則的觸發條件，執行第一條成立的規則。
這種寫法對彈窗、掉線、載入延遲等意外狀況天生有抵抗力。
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
from .config import LOG_DIR, resource_file
from .vision import Match, Region

log = logger.get("engine")


class ScriptError(RuntimeError):
    """腳本定義有誤。"""



def _option_reason(spec: str) -> str:
    """把 when_option 寫成人看得懂的條件，用在「這條規則為何不啟用」的訊息。"""
    if "=" in spec:
        key, _, val = spec.partition("=")
        return f"{key.strip()} = {val.strip()}"
    if spec.startswith("!"):
        return f"{spec[1:]} = false"
    return f"{spec} = true"


def _state_label(rule_name: str) -> str:
    """把規則名稱縮成狀態標籤，例如「配對中 → 留在原地等待」取「配對中」。

    純攔截規則的名稱前半段本來就是在描述當下的狀態，拿來當等待訊息剛好。
    """
    return rule_name.split("→")[0].strip() or rule_name


def _xy(arg: Any, default: tuple[int, int] | None = None) -> tuple[int | None, int | None]:
    """從動作參數取出一組座標。

    YAML 裡 `tap_match: []` 和 `tap_match:` 都表示「沒有參數」，
    這裡統一處理，避免對空清單取索引。
    """
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
    # 前置條件，這些模板必須全部存在。用來表達「在某個畫面上，而且某個東西不在」
    # ——例如「面板開著但開關沒開」。一律全畫面搜尋，不受 region 限制。
    require: list[str] = field(default_factory=list)
    # 量某個顏色在區域裡佔了多少寬度，判斷「長度在講話」的元素（順序條、血條）。
    # 這種元素裁模板會裁到會變的內容，改量固定的 UI 顏色。欄位見 measure_raw()。
    measure: dict[str, Any] | None = None
    # 有多個匹配時挑哪一個：best 分數最高（預設）、lowest / highest 最下 / 最上、
    # first / last 最左 / 最右，或直接給數字＝由左數來第幾個（1 起算）。
    pick: str | int = "best"
    # 給了多個模板時，pick 要不要跨模板一起比。預設 false——那時 template 的
    # **順序就是優先度**（羈絆那條「紅 ❗ 排前面等於先領完再派」靠的就是這個）。
    # 只有「這幾個模板是同一種東西的不同長相」時才該打開。
    pick_across: bool = False
    # 綁定 config 的 options 開關，前面加 ! 表示反向，也可以寫 key=value
    when_option: str | None = None
    # 綁定 set_flag 設出來的旗標，前面加 ! 表示反向；給清單就是全部都要成立。
    # 用來把「在 A 畫面看到的事實」帶到 B 畫面判斷——兩張畫面沒有共同元素時，
    # 條件本身表達不了（副本的「這一級已經是天花板了嗎」就是這種形狀）。
    when_flag: list[str] = field(default_factory=list)
    actions: list[dict[str, Any]] = field(default_factory=list)
    cooldown: float = 0.0                # 觸發後多久內不再觸發（秒）
    once: bool = False                   # 整場只觸發一次
    max_fires: int = 0                   # 最多觸發幾次，0 表示不限
    # 「今天」最多觸發幾次——和 max_fires 的差別是**跨執行保留**。max_fires 每輪
    # 重置，拿它當每日上限的話，補跑或手動重跑就會重新計數（設 3 場跑兩輪＝6 場）。
    # ⚠ 只在「那個數字畫面上看不到」時才用，細節見 core/dailystate.py。
    max_fires_daily: int = 0
    # 條件必須「持續成立」這麼多秒才真的觸發。兜底規則一定要設，否則畫面轉場
    # 那一瞬間就會被當成「卡住了」而誤動作。
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

    def mark_fired(self, now: float) -> None:
        self._last_fired = now
        self._fires += 1
        if self.max_fires_daily:
            self._today = dailystate.add(self._daily_key)


@dataclass
class Script:
    """一份腳本：規則表，加上收尾動作與脫困門檻。"""

    name: str
    package: str | None
    rules: list[Rule]
    # 整輪跑完（收工或達到次數）後無條件執行的收尾動作，例如回到家園待命。
    # 無條件執行代表沒有 template 守著畫面是什麼，所以裡面只能用 tap_template。
    on_finish: list[dict[str, Any]] = field(default_factory=list)
    # 畫面靜止這麼多秒就按返回鍵脫困
    stuck_timeout: float = 90.0
    # 一輪最多跑幾分鐘，0 表示不限。這是「規則彼此打架而無限循環」的安全網——
    # 那種情況畫面一直在變，stuck_timeout 永遠不會成立，排程會被整個擋住。
    # ⚠ 只給「一輪本來就該很短」的腳本設。副本要打十幾分鐘、討伐等人要半小時，
    #   設了會在戰鬥中途被切斷。
    max_minutes: float = 0.0
    # 等待時附在狀態後面的即時資訊，形狀和 log_match 一樣。用在「會一路變動」的
    # 值（副本戰鬥中的評級）：寫進紀錄只會洗版，附在狀態列剛好。
    status: dict[str, Any] = field(default_factory=dict)

    def referenced_templates(self) -> set[str]:
        """列出腳本用到的所有模板名稱，供 doctor 檢查是否齊全。

        只認真正會拿去比對的欄位，以及 tap_template / tap_all / log_match 的
        參數；log、screenshot 那些字串參數不是模板。
        """
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
        # ⚠ 代入設定值要排在建立 Rule **之前**：sustain 那些欄位在建 Rule 時就
        #   會 float()，字串形式的 "${...}" 撐不到那一步。
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
                    pick=item.get("pick", "best"),
                    pick_across=bool(item.get("pick_across", False)),
                    when_option=item.get("when_option"),
                    when_flag=as_list(item.get("when_flag")),
                    actions=item.get("do") or [],
                    cooldown=float(item.get("cooldown", 0)),
                    once=bool(item.get("once", False)),
                    max_fires=int(item.get("max_fires", 0)),
                    max_fires_daily=int(item.get("max_fires_daily", 0)),
                    sustain=_seconds(item, "sustain"),
                )
            )

        # 每日計數的鍵。⚠ 一定要帶腳本名當前綴——不同腳本可能有同名的規則，
        # 共用一個鍵的話會互相扣次數，而且從紀錄上完全看不出來。
        for rule in rules:
            if rule.max_fires_daily:
                rule._daily_key = f"{Path(name).stem}/{rule.name}"
                rule._today = dailystate.get(rule._daily_key)

        # reset_fires 指的是「別條規則的名字」，打錯的話執行時什麼都不會發生，
        # 而紀錄上完全看不出來——所以在這裡就擋下來。
        known = {r.name for r in rules}
        for rule in rules:
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

        # when_flag 指的是別條規則用 set_flag 設出來的名字。打錯的話那條規則會
        # **永遠不成立**，而紀錄上只會看到「沒有規則成立」——和 reset_fires 同一
        # 個理由，在載入時就擋下來。
        settable: set[str] = set()
        for rule in rules:
            for action in rule.actions:
                for verb in ("set_flag", "clear_flag"):
                    arg = action.get(verb)
                    if arg:
                        settable |= {arg} if isinstance(arg, str) else set(arg)
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
        )


def _seconds(item: dict[str, Any], key: str) -> float:
    """取秒數。`sustain: 300` 與 `sustain_minutes: 5` 是同一件事。

    要等好幾分鐘的規則寫成秒很難讀，而那幾條正是使用者最可能想調的。
    """
    if item.get(key) is not None:
        return float(item[key])
    minutes = item.get(f"{key}_minutes")
    return float(minutes) * 60 if minutes is not None else 0.0


_VAR_RE = re.compile(r"^\$\{(\w+)(?::([^}]*))?\}$")


def resolve_vars(node: Any, options: dict[str, Any]) -> Any:
    """把腳本裡的 `${設定名}` / `${設定名:預設值}` 換成實際的值。

    腳本負責說明這個數字是什麼、預設多少，設定檔負責覆蓋它：

        sustain: "${raid_join_sustain:20}"     設定檔沒填就用 20

    ⚠ 一定要帶預設值。少了的話，還沒有這個鍵的舊 config.yaml 一升級就載入失敗，
      而使用者根本沒改過任何東西。

    ⚠ 只認「整個字串就是一個變數」，不做字串內嵌（`"等 ${n} 秒"` 不會被代換）。
      這是為了保留型別：代出來的 20 必須是數字而不是 "20"。
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


# `wait_for` 最多等幾秒。這個動作是用來跨過換頁與載入的空檔（實測討伐加入戰鬥後
# 的載入約十幾秒），不是用來等一場戰鬥——等不到就往下走，別把收尾卡住。
WAIT_FOR_TIMEOUT = 25.0


def _as_index(pick: Any) -> int | None:
    """把 pick 讀成「由左數來第幾個」，不是數字就回 None（交給具名策略處理）。

    ⚠ 要擋掉 bool。Python 的 True 是 int 的子類，不擋的話 `pick: true`
      會被當成「第 1 個」而不是報無效值。
    """
    if isinstance(pick, bool):
        return None
    if isinstance(pick, int):
        return pick if pick >= 1 else None
    if isinstance(pick, str) and pick.strip().isdigit():
        return max(int(pick), 1)
    return None


# 順序條的「單位數 ↔ 人數」換算。校準自五個真值點（見 CLAUDE.md 的對照表），
# 五點都落在 ±1.5 個單位內。⚠ 這是估計值，誤差約 ±2～3 人。
UNITS_PER_PLAYER = 2.25
UNITS_BASE = 5.75


def units_for_players(players: float) -> float:
    """幾個人 → 順序條上大約幾個單位。使用者填人數，腳本比的是單位數。"""
    return UNITS_PER_PLAYER * float(players) + UNITS_BASE


def players_for_units(units: float) -> float:
    """反過來換算，用在把量到的數字寫成人話。"""
    return (float(units) - UNITS_BASE) / UNITS_PER_PLAYER


def _threshold(spec: dict[str, Any], key: str) -> float | None:
    """取一個門檻值。`at_least` 是單位數，`at_least_players` 是人數（自動換算）。

    讓設定檔可以用「幾個人」表達——「28 個單位」對使用者沒有意義，而那個數字
    背後就是「大約 10 人」。
    """
    if spec.get(key) is not None:
        return float(spec[key])
    people = spec.get(f"{key}_players")
    return units_for_players(people) if people is not None else None


# 具名的挑選策略。`min()` 取最小，所以要往「畫面下方／右邊」挑的就取負值。
# ⚠ 抽到模組層級是為了讓 pick_across 也用同一份——兩邊各寫一份的話，
#   「跨模板挑最下面」和「單一模板挑最下面」有一天會不一致。
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

    ⚠ 這個函式與 measure_ok / apply_options 放在模組層級，是為了讓 explain 與
      實際執行共用同一套判斷。除錯工具若和執行不一致，看到的結論就是假的。
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
    """數值加上單位。units 是估計值，留一位小數以免看起來像精確計數。

    門檻若是用人數設定的，把換算後的人數一起寫出來——「23 個單位」對讀紀錄的人
    沒有意義，那是內部指標，而使用者在設定檔裡填的是人數。格式和
    describe_measure 一致（`約 23.0 個單位／約 7.7 人`）。

    ⚠ 只在門檻用 `*_players` 表達時才換算。那是「這個量測講的是人數」唯一明確
      的訊號；單看 `metric: units` 不夠，換算式只對公會討伐的順序條校準過。
    """
    if spec.get("metric") != "units":
        return f"{value:.0f} px"
    text = f"約 {value:.1f} 個單位"
    if spec.get("at_least_players") is None and spec.get("at_most_players") is None:
        return text
    return f"{text}／約 {max(0.0, players_for_units(value)):.1f} 人"


def describe_measure(spec: dict[str, Any]) -> str:
    """把 measure 的門檻寫成人看得懂的一句話，給 explain 與紀錄用。

    門檻若是用人數設定的就一併寫出人數，讓紀錄對得上設定檔裡填的數字。
    """
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
    """平滑讀數旁邊那段診斷字串：這一幀量到多少、平滑視窗填了幾格。

    `smooth: N` 取的是最近 N 次的中位數，換算成時間是 N × 每輪的秒數——視窗沒
    填滿（或剛填滿）時，平滑值裡還混著進畫面之前的低讀數，會比眼睛看到的少一截。
    少了這兩個數字就分不出「量錯了」和「還在追畫面」，那兩件事的修法完全不同。
    """
    if window <= 1:
        return ""
    unit = _measure_unit(spec)
    return f"單幀 {raw:.1f} {unit}、視窗 {filled}/{window}；"


def apply_options(rules: list[Rule], options: dict[str, Any]) -> list[Rule]:
    """依 config 的開關停用不適用的規則，回傳被停用的那些。

    `when_option` 支援三種寫法：
        like_teammates          該開關為 true 才啟用（設定檔沒有這個鍵也算 true）
        !claim_reward           該開關為 false 才啟用
        buy_counts=2            該設定值等於 2 才啟用
        buy_arena_tickets=true  同上，但這是布林——用途見下面的 ⚠

    ⚠ **會花掉資源的規則一定要用 `=` 那種寫法。** 正向寫法在設定檔缺這個鍵時
      預設為 true（為了讓舊 config.yaml 不必改就能跑），而新增一個「會花晨星」
      的功能若照這樣預設開啟，使用者根本沒同意就被花掉了。`=` 的語意是
      「設定檔明確寫成這個值才啟用」，缺鍵就是不啟用。
    """
    disabled = []
    for rule in rules:
        spec = rule.when_option
        if not spec:
            continue

        if "=" in spec:
            # 值比較。沒設定這個項目就當作不符合——數值沒有合理的預設值，
            # 布林則是刻意要「明講才算數」（見上面的 ⚠）。
            #
            # ⚠ 比較要忽略大小寫。YAML 的 true 讀進來是 Python 的 True，
            #   str() 之後是 "True"，和腳本裡寫的 `=true` 對不起來。
            key, _, want_value = spec.partition("=")
            actual = options.get(key.strip())
            ok = (actual is not None
                  and str(actual).strip().lower() == want_value.strip().lower())
        else:
            key, want = spec, True
            if key.startswith("!"):
                key, want = key[1:], False
            ok = bool(options.get(key, True)) == want

        if not ok:
            rule._disabled = True
            disabled.append(rule)
    return disabled


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
        # 兩層停止旗標，語意不同：_stop 是「這一輪跑完了」（次數到、腳本收工），
        # stop_event 是外部要求整個程式結束（GUI 按下停止、視窗關閉）。
        # 分開才不會在 reset() 準備下一輪時，把使用者剛按下的停止清掉。
        self.yielded = False        # 上一輪是不是「讓位」而不是自己收工
        self._stop = False
        self._stop_event = stop_event or threading.Event()
        self._finishing = False         # 正在跑 on_finish，此時等待不可被打斷
        # 等待狀態的即時回報。終端機是原地更新那一行，GUI 則是狀態列——
        # 兩者要的是同一份資訊，所以在同一個地方發出去。
        self._status_hook = status_hook
        self._last_change = time.time()
        self._prev_frame: np.ndarray | None = None
        self._until: datetime | None = None      # 到這個時刻就讓位給下一個腳本
        self._waiting_name: str | None = None
        self._waiting_block_start = 0.0  # 這一整段「沒有動作」是何時開始的
        self._waiting_logged = 0.0       # 上次寫心跳到紀錄檔的時間
        self._measure_logged: dict[str, float] = {}   # 各 measure 上次寫紀錄的時間
        # 各 measure 最近幾次的讀數，給 smooth 取中位數用
        self._measure_history: dict[str, deque[float]] = {}
        # 只有真正的終端機才用 \r 原地更新；輸出被導向檔案或管線時 \r 只會製造
        # 一堆亂碼，那種情況退回節流寫紀錄。
        self._tty = bool(getattr(sys.stdout, "isatty", lambda: False)())
        self._options_logged = False     # 「略過規則」只寫第一輪
        self._last_log_text = ""         # log_text 讀到一樣的就不重寫
        # 這一輪已經成立的旗標。和 max_fires 一樣是「這一輪發生過什麼」的記憶，
        # 差別是它記的是**看到的事實**而不是**觸發過幾次**。
        self._flags: set[str] = set()
        self._apply_options(self.cfg.options)

    def _apply_options(self, options: dict[str, bool]) -> None:
        """依 config 的開關停用不適用的規則。

        ⚠ 只在第一輪寫紀錄。設定在執行中改不了，每輪重印同樣幾行只是佔版面。
        """
        disabled = apply_options(self.script.rules, options)
        if self._options_logged:
            return
        self._options_logged = True
        for rule in disabled:
            log.info("略過規則「%s」（需要設定 %s）", rule.name,
                     _option_reason(rule.when_option))

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
        # 用指派而不是 clear()：測試常常拿 Engine.__new__ 造一個沒跑過 __init__
        # 的引擎，那種引擎沒有這個欄位。
        self._flags = set()
        for rule in self.script.rules:
            rule._fires = 0
            rule._last_fired = 0.0
            rule._disabled = False
            # ⚠ 每日上限**不能跟著歸零**——那正是它和 max_fires 的差別。
            #   從狀態檔取回今天已經觸發的次數。
            if rule.max_fires_daily:
                rule._today = dailystate.get(rule._daily_key)
        self._apply_options(self.cfg.options)

    # ---------- 主迴圈 ----------

    def run(self, until: datetime | None = None) -> int:
        """跑到腳本收工。`until` 是「下一個排程時刻」，到了就讓位。

        ⚠ 沒有 `until` 的話，永不收工的腳本會把排程整個擋住，而紀錄上看起來
          一切正常。

        ⚠ 讓位的檢查點在「完成一次」之後（`count` 動作裡），不是每一輪。時間到
          就當場停的話很可能停在戰鬥中途，收尾會把人退出戰鬥、那次次數就白費了。
        """
        self._until = until
        # 不再寫一行「開始執行腳本 X」：呼叫端的分隔線已經寫了腳本名稱與目標次數。
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
                    log.warning("已經跑了 %.0f 分鐘還沒收工，先收尾讓位給下一個腳本",
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
                        # 沒有動作的規則是「純攔截」：配對中、戰鬥中就該待著。
                        # 規則名稱「→」前面那段就是狀態，拿來當等待訊息。
                        self._log_waiting(_state_label(rule.name), screen)
                else:
                    # 沒有任何規則成立。該等的狀態都有攔截規則，所以走到這裡
                    # 通常是轉場或載入中的短暫空檔。
                    self._log_waiting("等待畫面變化", screen)

                # ⚠ tick 是「每輪之間至少隔這麼久」，不是「每輪額外睡這麼久」。
                #   一輪的截圖與比對本來就要一兩秒（實測自動副本 59 條規則約
                #   1.8 秒），再固定加睡一秒等於把反應時間拉長一半，而使用者
                #   看到的就是「換頁之後很久才動作」。
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

    def _sleep(self, seconds: float) -> bool:
        """可被中斷的等待，回傳「是否被要求停止」。GUI 沒有 Ctrl+C 可送，
        所以等待本身要醒得過來。

        ⚠ 收尾期間例外，一律睡好睡滿。停止的當下 stop_event 已經是 set 的，
          若收尾的等待跟著立刻返回，逐層退場的每一步就會擠在一起送出——那些
          等待正是在讓換頁動畫跑完，少了它會把上一頁的座標點在新頁上。
        """
        if self._finishing:
            time.sleep(seconds)
            return False
        return self._stop_event.wait(seconds)

    def _run_on_finish(self) -> None:
        """跑完一輪後的收尾，例如回到家園待命，方便下一輪或人工接手。

        不另外寫「執行收尾動作」：on_finish 的第一個動作就是自己的 log。

        ⚠ **逐步回報進度給狀態列。** 收尾實測要 14～18 秒（那些 `wait` 是在讓
          換頁動畫跑完，省不掉），而狀態列若停在一句不動的「正在執行收尾動作」，
          使用者看到的就是「按下停止之後當掉了」——回報就是這樣來的。
          只要那行字一直在變，同樣的 15 秒就不會被當成當機。
        """
        if not self.script.on_finish or self.dry_run:
            return
        self._finishing = True
        try:
            screen = self.device.screencap()
            steps = self.script.on_finish
            for i, action in enumerate(steps, 1):
                self._emit_status(f"收尾中　第 {i} 步，共 {len(steps)} 步")
                self._execute([action], screen, None)
        except Exception as e:                      # 收尾失敗不該影響主要結果
            log.warning("收尾動作未完成：%s", e)
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
        """等待時要附在狀態後面的即時資訊，例如「評級 A」。

        ⚠ 認不出來就整個不顯示，不要寫「評級 （認不出）」。這段每輪都會跑，而
          大部分時間根本不在那個畫面上。（`log_match` 相反：那是寫紀錄，
          「讀不到」本身就是要留下的事實。）
        """
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
        """回報等待狀態。等待可能持續十幾分鐘，兩個輸出各有分工：

          終端機　→ 固定在同一行原地更新，狀態與經過時間隨時看得到
          紀錄檔　→ 只留心跳（預設 5 分鐘一行）與離開等待時的總結

        ⚠ 狀態切換不寫紀錄檔。副本裡「戰鬥中 → 載入中 → 選下一關」本來就頻繁
          交替，每次切換都寫一行會把紀錄刷滿而蓋掉真正的重點。

        ⚠ 經過時間算的是「這一整段等待」而不是「目前這個狀態」。後者會在每次
          切換狀態時歸零，看起來像打到一半又重新計時。

        沒有原地更新可用時（輸出被導向檔案或管線）只靠心跳，間隔自動縮短。
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
            # ⚠ 要先清掉原地更新的那一行，否則心跳會接在沒有換行的進度行後面。
            #   不能改用 _end_waiting_line：那個會把累計歸零，秒數就重新算了。
            self._clear_waiting_line()
            log.info("等待中　%s（目前狀態：%s）", elapsed, name)

        # 即時資訊只附在「隨時看得到」的兩個地方，不進紀錄檔——心跳是 5 分鐘
        # 一行的摘要，不該混進會一直變的值。
        extra = self._status_extra(screen)
        shown = f"{name}　{extra}" if extra else name
        if self._tty:
            self._draw_waiting_line(logger.transient("engine", f"{shown}　{elapsed}"))
        self._emit_status(f"{shown}　{elapsed}")

    def _emit_status(self, text: str) -> None:
        """把目前狀態送給外部觀察者（GUI 狀態列）。

        傳的是已經排好的字串，呼叫端直接顯示。掛鉤壞掉不該拖垮執行，吞掉例外。
        """
        if self._status_hook is None:
            return
        try:
            self._status_hook(text)
        except Exception:
            pass

    def _draw_waiting_line(self, line: str) -> None:
        """在同一行原地更新等待訊息。

        優先用 ANSI 的「清除到行尾」：補空白會讓游標停在文字後面幾格。
        """
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
        """收掉原地更新的那一行，等超過 60 秒才留一筆總結（短暫轉場不值得留紀錄）。

        ⚠ 一定要在輸出其他訊息之前呼叫，否則那些訊息會接在沒有換行的進度行後面。
        """
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
        # 旗標排在最前面：不成立時連 sustain 的計時都不該累加。
        # ⚠ selftest 借用這個函式（Engine.__new__，沒跑 __init__），那種引擎沒有
        #   旗標可查。那支是一張畫面一張畫面地驗規則，本來就沒有「上一頁看到
        #   什麼」，所以一律當成成立，不要讓它把好規則判成落空。
        flags = getattr(self, "_flags", None)
        if rule.when_flag and flags is not None:
            for want in rule.when_flag:
                if (want[1:] in flags) if want.startswith("!") else (want not in flags):
                    return False, None

        if rule.require and not all(
            self._find(screen, name, th) for name in rule.require
        ):
            return False, None

        if rule.measure and not self._measure(screen, rule):
            return False, None

        if rule.template:
            if rule.pick_across and len(rule.template) > 1:
                # 每個模板各自挑出的贏家再比一次，就是全域的那一個——
                # lowest / highest / first / last 都是取極值，所以這樣等價。
                #
                # 需要它的形狀是「同一種東西的兩張臉」：副本列表上每張卡片都有
                # 評級標章，只是打過的是「最高評級」、沒打過的是「暫無評級」，
                # 而我們要的是「最下面那張卡片」，跟標章是哪一種無關。
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

        if rule.require or rule.measure:
            # 沒給 template / absent 的規則：前置條件與量測都過就成立
            return True, None

        return False, None

    def _measure(self, screen: np.ndarray, rule: Rule) -> bool:
        """評估 measure 條件，並每 30 秒把量到的數值寫進紀錄（門檻要靠實機資料調）。

        `smooth: N` 對最近 N 次讀數取中位數。估計值單幀會跳（相鄰可差到 20 個
        單位），非平滑不可。

        ⚠ 每輪只能取樣一次。_match_rule 會掃兩遍規則（sustain 預掃 ＋ 主掃），
          取兩次樣的話滑動視窗只涵蓋一半的時間，所以結果快取在 _measure_frame。
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
        # selftest 只借用判斷邏輯（Engine.__new__，沒跑 __init__），那種引擎
        # 沒有紀錄用的欄位：量測照算，但不寫紀錄。
        seen = getattr(self, "_measure_logged", None)
        if label and seen is not None:
            now = time.time()
            if now - seen.get(rule.name, 0.0) >= 30:
                first = rule.name not in seen
                seen[rule.name] = now
                self._end_waiting_line()
                # ⚠ 門檻只在第一筆寫。它整輪都不會變，每 30 秒重述一次會讓那幾行
                #   長得一模一樣，真正在動的數值反而看不出來。
                # 平滑值滯後於畫面，所以單幀讀數與視窗填了幾格要一起寫：兩者
                # 差很多而視窗還沒填滿，就是「讀數還在追畫面」而不是量錯了。
                trace = _measure_trace(raw, filled, window, rule.measure)
                if first:
                    log.info("%s：%s（%s門檻 %s，%s）", label,
                             _measure_text(value, rule.measure), trace,
                             describe_measure(rule.measure),
                             "符合" if ok else "不符合")
                else:
                    log.info("%s：%s（%s%s）", label,
                             _measure_text(value, rule.measure), trace,
                             "符合" if ok else "不符合")
        return ok

    def _match_rule(self, screen: np.ndarray) -> tuple[Rule, Match | None] | None:
        """回傳第一條成立的規則，以及它的比對結果（若有）。"""
        # 同一張畫面的量測與比對都只算一次（下面會掃兩遍規則）
        self._measure_frame: dict[str, bool] = {}
        self._match_frame: dict[tuple, Any] = {}
        now = time.time()

        # ⚠ 有 sustain 的規則要先全部評估一次才能正確計時。只在輪到它時才算的話，
        #   畫面離開又回來時計時不會歸零，一成立就立刻觸發，等於沒有 sustain。
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
        """有快取的 vision.find，同一輪裡同一組參數只真的比對一次。

        ⚠ 全畫面的彩色比對一次要 85～125ms（實測 720x1280，模板 40x60 上下），
          而一輪要掃兩遍規則（sustain 預掃 ＋ 主掃），`btn_back_arrow`、
          `nav_home` 這種到處都在的模板還會跨規則重複——實測 raid 一輪要求
          64 次比對，其中只有 21 種不重複。這是主迴圈最大的一筆開銷。

        ⚠ 快取只在一輪之內有效（`_match_rule` 開頭重置），所以畫面換了不會拿到
          舊答案。動作裡的 `tap_template` 走的是 vision 而不是這裡，它本來就該
          對重新抓的畫面比對。
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

        # 數字＝由左數來第幾個（1 起算）。橫排的同類元素（競技場的四個對手）
        # 用 first / last 只表達得了兩端，而中間那幾個也是有意義的選擇。
        #
        # ⚠ 超出範圍時取最靠近的那一端，不要落空。畫面上有幾個是遊戲決定的，
        #   而規則落空會讓後面的兜底搶著動作。
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

    def _execute(
        self, actions: list[dict[str, Any]], screen: np.ndarray, match: Match | None
    ) -> None:
        for action in actions:
            for verb, arg in action.items():
                if self.dry_run and verb not in ("log", "screenshot", "wait", "count"):
                    log.info("[試跑] 略過動作 %s: %s", verb, arg)
                    continue
                self._do(verb, arg, screen, match)

    def _do(self, verb: str, arg: Any, screen: np.ndarray, match: Match | None) -> None:
        d = self.device

        if verb == "tap_match":
            if match:
                # 寫成 `tap_match: []` 或 `tap_match:` 都表示不偏移
                dx, dy = _xy(arg, default=(0, 0))
                cx, cy = match.center
                d.tap(cx + dx, cy + dy)
            else:
                log.warning("tap_match 沒有可用的比對結果")

        elif verb == "tap":
            x, y = _xy(arg)
            if x is None:
                log.warning("tap 需要 [x, y] 兩個座標，收到：%s", arg)
            else:
                d.tap(x, y)

        elif verb == "tap_template":
            # ⚠ 重新抓一張畫面。沿用規則觸發時的截圖會出事：動作清單裡的
            #   tap_template 前面常有 wait 或其他點擊，畫面早就換了。
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
            # 點掉畫面上所有符合的目標，例如結算頁每位隊友的按讚鈕。
            # 同樣要重新抓畫面，理由見上面的 tap_template。
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
            log.info("點掉畫面上 %d 個目標", hits)

        elif verb == "swipe":
            x1, y1, x2, y2 = (int(v) for v in arg[:4])
            dur = int(arg[4]) if len(arg) > 4 else 300
            d.swipe(x1, y1, x2, y2, dur)

        elif verb == "back":
            d.back()

        elif verb == "wait":
            self._sleep(float(arg))

        elif verb == "restart_app":
            # 最後手段：關掉遊戲再開起來，讓畫面回到「開機 → 家園」這條認得的路。
            #
            # 兜底按系統返回鍵解決不了兩種畫面：**返回鍵無效的結算頁**（只能點
            # 空白處），以及**按返回鍵反而會叫出來的確認框**——後者會變成開開關關
            # 的死循環（實測有使用者卡在「要退出觀戰狀態嗎?」17 分鐘、空按 26 次）。
            # 不認得的畫面永遠會有新的，所以要有一條不靠模板的退路。
            #
            # ⚠ 只掛在兜底鏈的**最後一條**，而且前面那條要先用掉 max_fires。
            #   重開遊戲要 152 秒，不該在「其實再等一下就會好」的時候動用。
            pkg = self.script.package
            if not pkg:
                log.warning("腳本沒有指定 package，無法重開遊戲")
            else:
                log.warning("連續脫困失敗，重新啟動遊戲")
                d.stop_app(pkg)
                self._sleep(3)
                d.launch_app(pkg)
                # ⚠ 這裡要等到**過得了全黑那段**。遊戲重開後前 35 秒是全黑，
                #   什麼模板都認不到——而兜底的條件（那些模板全都不在）在黑畫面
                #   上一直成立。等太短就會在還沒開起來時又觸發一次重開，
                #   而且永遠escape不了：實測有使用者 08:03 卡進去，每 30 秒重開
                #   一次，跑了一個多小時還在原地。
                self._sleep(float(arg) if arg else 45)
                # ⚠ 畫面已經被我們自己換掉了，所有 sustain 的計時都要歸零。
                #   `sustain` 累加的依據是「條件連續成立多久」，而黑畫面讓兜底
                #   的條件持續為真——不歸零的話下一輪就又滿了。
                for rule in self.script.rules:
                    rule._since = 0.0
                self._last_change = time.time()

        elif verb == "wait_for":
            # 等到畫面上出現其中一個模板才往下走，最多等 WAIT_FOR_TIMEOUT 秒。
            #
            # `on_finish` 是無條件清單，沒辦法用規則去等一個畫面，而換頁前後常有
            # 幾秒的載入——固定 `wait:` 只能猜：猜短了整串動作全部空點，猜長了
            # 每一次收尾都白等。這個動作在畫面認得出來的那一刻就返回。
            #
            # ⚠ 這不是拿來等一場戰鬥或一次配對的。逾時就直接往下走，不報錯——
            #   後面的 tap_template 本來就是「找不到就不點」。
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

        elif verb == "count":
            self.completed += 1
            log.info("完成第 %d 次", self.completed)
            # 打完一場是最安全的讓位時機（見 run 的說明）
            if self._until and datetime.now() >= self._until:
                log.info("已到下一個排程時刻，這一輪先收工讓位")
                self._stop = True
                # ⚠ 讓位和「自己收工」要分得出來。讓位代表**該做的還沒做完**
                #   （次數還有、獎勵還沒領），排程那邊要把它排回去，等這一波
                #   排定時刻與補跑清完再接著跑。少了這個記號，副本讓位一次就
                #   等於整天只打到一半——而紀錄上每一行都正常。
                self.yielded = True

        elif verb == "screenshot":
            name = arg if isinstance(arg, str) else datetime.now().strftime("%H%M%S")
            path = LOG_DIR / "frames" / f"{name}.png"
            vision.imwrite_unicode(path, screen)
            log.info("已存截圖：%s", path)

        elif verb == "log_text":
            # 用系統內建 OCR 讀畫面上的文字寫進紀錄，不必為每個副本裁模板。
            #
            # 寫法（每個欄位可以只給 region，或給 dict 帶參數）：
            #   log_text:
            #     選擇副本: {region: [110, 174, 510, 64], binary: 210, scale: 3}
            #     難度: {region: [30, 798, 170, 34], scale: 4, strip: 副本獎勵}
            #
            # 欄位名稱自己當標籤，會寫成「選擇副本：月之宮殿　難度：惡夢」。
            # 只影響紀錄不影響判斷，讀不到就寫「讀不到」帶過。
            #
            # ⚠ 讀出來和上一次一樣就不重讀也不重寫。這條規則會在等配對的期間
            #   反覆觸發，而每次 OCR 要開一個 PowerShell（約 1 秒）——同一場
            #   副本重覆讀十幾次，紀錄上也是十幾行一模一樣的字。
            from core import ocr

            screen = d.screencap()
            parts = []
            for label, spec in (arg or {}).items():
                spec = {"region": spec} if isinstance(spec, list) else dict(spec)
                strip = spec.pop("strip", None)
                text = ocr.read(screen, **spec)
                for junk in ([strip] if isinstance(strip, str) else (strip or [])):
                    text = text.replace(junk, "")
                parts.append(f"{label}：{text.strip() or '（讀不到）'}")
            line = "　".join(parts)
            if line != self._last_log_text:
                self._last_log_text = line
                log.info("%s", line)

        elif verb == "log_match":
            # 把「畫面上是哪一種」寫進紀錄。給一組「顯示文字 → 模板」，挑分數
            # 最高且過門檻的那個。
            #
            # 寫法：
            #   log_match:
            #     評級: {region: [270, 140, 200, 220],
            #            of: {S: rank_s, A: rank_a, B: rank_b}}
            #
            # 和 log_text 一樣只影響紀錄、不影響判斷：認不出來就寫「認不出」，
            # 規則該做的事照做，少一張模板不會讓流程卡住。
            #
            # ⚠ region 幾乎一定要給。單一個字母不框住的話，畫面別處的深色圖形
            #   也可能比中。
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
            # 不加前綴。這是規則自己要補充的話，前面已經有「觸發規則：X」交代
            # 是誰在講，再標一次「腳本訊息」只是多一段要跳過的字。
            #
            # 也因此：只在「規則名稱沒說完」的時候才寫 log（例如等了幾分鐘、
            # 依據什麼數字決定），純粹重述規則名稱的那種一律不要。
            log.info("%s", arg)

        elif verb == "reset_fires":
            # 把指定規則的 max_fires 計數歸零，讓它可以再觸發一次。
            #
            # max_fires 本身就是引擎唯一的「這一輪發生過什麼」的記憶（daily 的
            # 聖獸／雙影換手就是靠它）。少了歸零的手段，那份記憶只能單向消耗，
            # 表達不了「條件變了，重來一次」——競技場的「贏了就回頭挑最強的」
            # 正是這種形狀。
            #
            # ⚠ 規則名稱有錯會在載入時就報錯（Script.load 檢查過），不是執行到
            #   這裡才靜靜地什麼都不做。
            names = {arg} if isinstance(arg, str) else set(arg or [])
            for r in self.script.rules:
                if r.name in names:
                    r._fires = 0

        elif verb == "set_flag" or verb == "clear_flag":
            # 旗標讓「上一個畫面看到的事實」影響後面的判斷。副本的領獎就是這種
            # 形狀：該不該領要看「更高的難度還開不開得了」，而那件事只寫在詳情
            # 頁上，結算頁完全看不到。
            #
            # ⚠ 名稱有錯會在載入時就報錯（Script.load 檢查過）。
            names = {arg} if isinstance(arg, str) else set(arg or [])
            if verb == "set_flag":
                self._flags |= names
            else:
                self._flags -= names

        elif verb == "finish":
            # 不寫紀錄：觸發的規則名稱（「…→ 收工」）已經說了為什麼要結束，
            # 緊接著 on_finish 的第一行還會再說一次「本輪結束」。
            self.stop()

        else:
            log.warning("未知的動作：%s", verb)
