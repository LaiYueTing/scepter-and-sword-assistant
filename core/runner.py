"""排程執行：依設定輪流跑啟用的腳本，命令列與介面共用。

流程是「啟動先跑一輪 → 跑完找最近的下一個時刻 → 休眠 → 重新連線」。
"""

from __future__ import annotations

import threading
from datetime import datetime
from typing import Callable

from . import logger
from .adb import AdbError, Device
from .config import VERSION, Config, TaskConfig, resource_files
from .engine import Engine, Script

log = logger.get("main")

# 一輪中途出錯之後，等幾秒、重新連線再跑一次，最多連續重試幾次。
RETRY_LIMIT = 2
RETRY_DELAY = 30
# 到點重新連線失敗時重試幾次、隔幾秒。全部試完約 4 分鐘。
CONNECT_RETRIES = 3
CONNECT_RETRY_DELAY = 30


def next_scheduled(
    tasks: list[TaskConfig], now: datetime | None = None
) -> tuple[datetime, TaskConfig] | None:
    """在所有腳本中挑出最近的下一個 (時刻, 腳本)，沒有排程就回傳 None。"""
    best = None
    for task in tasks:
        when = task.next_run(now)
        if when and (best is None or when < best[0]):
            best = (when, task)
    return best


def _pretty_wait(seconds: float) -> str:
    """把等待時間寫成「幾小時幾分」的形式。"""
    s = int(max(0, seconds))
    if s < 60:
        return f"{s} 秒"
    if s < 3600:
        return f"{s // 60} 分"
    return f"{s // 3600} 小時 {s % 3600 // 60:02d} 分"


class Runner:
    """把「一組腳本 + 各自的排程」跑起來，可以從外面叫停。"""

    def __init__(
        self,
        cfg: Config,
        tasks: list[TaskConfig],
        one_shot: bool = False,
        dry_run: bool = False,
        stop_event: threading.Event | None = None,
        status_hook: Callable[[str], None] | None = None,
        interactive: bool = False,
        task_hook: Callable[[str, str, str], None] | None = None,
    ):
        self.cfg = cfg
        self.tasks = tasks
        self.one_shot = one_shot
        self.dry_run = dry_run
        self.stop_event = stop_event or threading.Event()
        # 腳本內部名稱 → 中文名，讀進腳本之後才有。
        self._titles: dict[str, str] = {}
        self.status_hook = status_hook
        # (腳本名, 狀態, 說明)。介面用它更新任務卡，命令列不接這個。
        self.task_hook = task_hook
        # 只有終端機才提示 Ctrl+C
        self.interactive = interactive
        # 要立刻跑的腳本（介面上的「虛空裂縫」按鈕）。
        self._injected: list[TaskConfig] = []
        # 是否正在等下一個排定時刻
        self.waiting = False
        # 正在跑的那一輪（腳本名, 引擎），給 abort() 用
        self._running: tuple[str, Engine] | None = None

    # ---------- 對外 ----------

    def stop(self) -> None:
        """要求結束。等待中的引擎會在一個 tick 內醒來，結束程序照常執行。"""
        self.stop_event.set()

    def inject(self, task: TaskConfig) -> bool:
        """加入一個不在排程裡的腳本跑一輪。回傳 True 代表會立刻開始。

        排程等待中會立刻執行，跑完回去等下一個時刻；正在跑別的腳本時接在那一輪後面（回傳 False）。

        ⚠ 不讓出執行權（`until=None`），中途經過的排定時刻由 _passed_during() 接住。
        """
        self._injected.append(task)
        return self.waiting

    def abort(self, name: str) -> bool:
        """中斷指定的腳本：排隊中的移除、執行中的立刻結束（不跑結束程序），排程照常。

        回傳是否真的中斷到。整個排程要結束用 `stop()`。
        """
        pending = [t for t in self._injected if t.name == name]
        for t in pending:
            self._injected.remove(t)
        if self._running is not None and self._running[0] == name:
            self._running[1].abort()
            return True
        return bool(pending)

    def run(self) -> int:
        """依排程輪流執行，回傳結束碼。腳本讀不到會拋 ScriptError。"""
        # ⚠ 先讀腳本再印設定說明（要寫中文名）；讀不到時仍先印完設定再拋。
        try:
            scripts = {t.name: Script.load(t.name, self.cfg.options)
                       for t in self.tasks}
        except Exception:
            self.describe_setup()
            raise
        self._titles = {name: s.name for name, s in scripts.items()}
        self.describe_setup()

        dev = Device(self.cfg)
        self._status("連線中")
        dev.connect()

        # 每個腳本一個引擎，保留規則狀態（觸發次數、sustain 計時），不可每輪重建。
        engines: dict[str, Engine] = {}
        scheduled = [t for t in self.tasks if t.times or t.weekly]

        # 待辦佇列：清單第一個，加上今天已過而不會再輪到的（_missed_today）。由 _take_next() 決定跑誰。
        queue: list[TaskConfig] = [self.tasks[0]]
        if self.cfg.runtime.catch_up:
            queue += [t for t in self._missed_today() if t is not queue[0]]
            if len(queue) > 1:
                log.info("補跑今天已過排定時刻的腳本：%s",
                         "、".join(self._title(t) for t in queue[1:]))
        current: TaskConfig | None = None
        # 每個腳本連續失敗了幾次（成功跑完一輪就歸零），見 _retry_after_failure
        failures: dict[str, int] = {}
        try:
            while not self.stop_event.is_set():
                if current is None:
                    current = self._take_next(dev, queue, scheduled)
                    if current is None:
                        break
                script = scripts.get(current.name)
                if script is None:
                    # 不在啟動清單裡的腳本，輪到才讀
                    try:
                        script = scripts[current.name] = Script.load(
                            current.name, self.cfg.options)
                    except Exception as e:
                        log.error("讀不到腳本「%s」：%s", current.name, e)
                        current = None
                        continue
                    self._titles[current.name] = script.name
                injected = current.name not in {t.name for t in self.tasks}
                log.info("───── 執行「%s」，目標次數：%s ─────",
                         script.name, current.repeat or "不限")

                engine = engines.get(current.name)
                if engine is None:
                    # ⚠ 輪到才建立引擎：建立時的「略過規則」訊息要排在分隔線之後。
                    engine = engines[current.name] = Engine(
                        dev, script, repeat=current.repeat, dry_run=self.dry_run,
                        stop_event=self.stop_event, status_hook=self.status_hook)
                else:
                    engine.reset()   # 同一個腳本再跑一輪，清掉上一輪的規則狀態
                self._task(current.name, "running", "執行中")
                self._running = (current.name, engine)
                started = datetime.now()
                # ⚠ 把下一個排定時刻交給引擎，到點自己讓出執行權，補跑期間也一樣。
                #   讓出之後那一格由 _passed_during() 接住並排到佇列最前面。
                nxt = next_scheduled(scheduled)
                failed = ""
                try:
                    engine.run(until=nxt[0] if nxt and not injected else None)
                except AdbError as e:
                    # ⚠ 一輪中途斷線不結束排程，重新連線後重試這一輪。
                    log.error("執行「%s」時中斷：%s", script.name, e)
                    failed = "連線中斷"
                    if self.one_shot:
                        raise
                except Exception as e:
                    # ⚠ 未預期的例外也不結束排程。一定要用 log.exception 留下 traceback。
                    log.exception("執行「%s」時發生未預期的錯誤：%s", script.name, e)
                    failed = "執行時發生錯誤"
                    if self.one_shot:
                        raise
                self._running = None
                spent = int((datetime.now() - started).total_seconds())
                # ⚠ 文字描述現在的狀態，不寫「剛才完成」：這句會一直留到下一輪。
                took = logger.pretty_seconds(spent)
                # ⚠ 出錯的那一輪不寫「這一輪沒有完成」，要與次數用盡的結束本輪區分開。
                if failed:
                    self._task(current.name, "error", f"{failed}（{took}）")
                else:
                    self._task(current.name, "done",
                               f"已完成 {engine.completed} 次（{took}）"
                               if engine.completed
                               else f"這一輪沒有完成（{took}）")

                if self.one_shot or self.stop_event.is_set():
                    break

                # 執行期間經過的排定時刻排到佇列最前面（見 _passed_during）。
                if self.cfg.runtime.catch_up:
                    late = [t for t in self._passed_during(
                                started, datetime.now(), current)
                            if t not in queue]
                    if late:
                        log.info("執行期間經過了「%s」的排定時刻，接著補跑",
                                 "」「".join(self._title(t) for t in late))
                        queue[:0] = late

                # 讓出執行權代表工作還沒做完，排回佇列最後面（late 比它急）。
                # ⚠ 不會無限讓出：until 一定是未來的時刻，重跑後至少要再走到一次 count。
                if (self.cfg.runtime.catch_up and engine.yielded
                        and current not in queue):
                    log.info("「%s」還沒做完就讓出執行權了，排到後面接著跑",
                             self._title(current))
                    queue.append(current)

                # 出錯的那一輪重新連線後排到最前面重試。
                # ⚠ 排在 late 前面：中斷的腳本可能把遊戲留在只有它認得的畫面上。
                if failed:
                    if self._retry_after_failure(dev, current, failures):
                        if current in queue:
                            queue.remove(current)
                        queue.insert(0, current)
                else:
                    failures.pop(current.name, None)

                current = None      # 下一輪跑誰交給 _take_next 決定
        except KeyboardInterrupt:
            log.info("使用者中斷，結束排程")

        self._status("已停止")
        return 0

    # ---------- 內部 ----------

    def _title(self, task: TaskConfig) -> str:
        """腳本的中文名稱（取自 `name:`），讀不到就用內部名稱。"""
        return self._titles.get(task.name, task.name)

    def _retry_after_failure(
        self, dev: Device, task: TaskConfig, failures: dict[str, int]
    ) -> bool:
        """一輪中途出錯之後要不要重試。等 RETRY_DELAY 秒、重新連線，連得上就回傳 True。

        ⚠ 連續失敗 RETRY_LIMIT 次或連不上就放掉這一格，等下一個排定時刻。
        """
        tries = failures.get(task.name, 0) + 1
        failures[task.name] = tries
        if tries > RETRY_LIMIT:
            log.warning("「%s」連續 %d 輪中途出錯，這一格放棄，等下一個排定時刻",
                        self._title(task), tries)
            failures.pop(task.name, None)
            return False
        log.info("「%s」%d 秒後重新連線再跑一次（第 %d 次重試，最多 %d 次）",
                 self._title(task), RETRY_DELAY, tries, RETRY_LIMIT)
        self._status(f"「{self._title(task)}」中途出錯，等候重試")
        if self.stop_event.wait(RETRY_DELAY):
            return False
        self._status("重新連線")
        try:
            dev.connect()
        except AdbError as e:
            log.error("重新連線失敗，「%s」這一格放棄：%s", self._title(task), e)
            failures.pop(task.name, None)
            return False
        return True

    def _missed_today(self, now: datetime | None = None) -> list[TaskConfig]:
        """今天已過排定時刻、而且今天不會再輪到的腳本，依時刻排序。

        不記錄今天跑過沒：腳本會進遊戲自己確認。

        ⚠ 今天還有下一格的不補跑，否則會把那一格的有限次數提前用掉。
        ⚠ `TaskConfig.catch_up = false` 的腳本不補跑。
        """
        now = now or datetime.now()
        clock = (now.hour, now.minute)
        found: list[tuple[tuple[int, int], TaskConfig]] = []
        for task in self.tasks:
            # ⚠ 用 times_on 而不是 times：每週的腳本只在那一天算。
            if not task.catch_up:
                continue
            today = task.times_on(now.date())
            passed = [t for t in today if t <= clock]
            if not passed:
                continue
            later = [t for t in today if t > clock]
            if later:
                log.info("「%s」今天還有 %02d:%02d 那一輪，不補跑",
                         self._title(task), *min(later))
                continue
            found.append((max(passed), task))
        return [task for _, task in sorted(found, key=lambda pair: pair[0])]

    def _due_soon(
        self, scheduled: list[TaskConfig], now: datetime | None = None
    ) -> tuple[datetime, TaskConfig] | None:
        """下一個排定時刻是否在 `catch_up_guard_minutes` 之內，是就回傳 (時刻, 腳本)，否則 None。

        設 0 表示關閉。
        """
        guard = self.cfg.runtime.catch_up_guard_minutes
        if guard <= 0:
            return None
        nxt = next_scheduled(scheduled, now)
        if nxt is None:
            return None
        now = now or datetime.now()
        return nxt if (nxt[0] - now).total_seconds() <= guard * 60 else None

    def _take_next(
        self, dev: Device, queue: list[TaskConfig], scheduled: list[TaskConfig]
    ) -> TaskConfig | None:
        """決定這一輪跑誰：排定時刻優先，其次是待補跑的。回傳 None 代表結束。

        ⚠ 啟動那一輪也要讓路，就算近的那個和佇列第一個是同一個腳本。
        ⚠ `--once` 不讓路。
        """
        if self._injected:
            return self._injected.pop(0)
        if not self.one_shot and queue and self._due_soon(scheduled) is not None:
            log.info("排定時刻近了，先讓它跑完再補跑（還有 %d 個待補：%s）",
                     len(queue), "、".join(self._title(t) for t in queue))
            task = self._wait_for_next(dev, scheduled)
            if task is not None:
                return task
            # 被要求停止、或已經沒有排程了，就回頭把佇列清一清
        if queue:
            return queue.pop(0)
        return self._wait_for_next(dev, scheduled)

    def _wait_for_next(
        self, dev: Device, scheduled: list[TaskConfig]
    ) -> TaskConfig | None:
        """睡到下一個排定時刻並重新連線，回傳該跑的腳本；沒有排程或被要求停止就回傳 None。

        ⚠ 連不上就放掉這一格，繼續等下一個時刻，不結束排程。
        """
        while not self.stop_event.is_set():
            # 每次都重新算：腳本可能跑了好幾個小時，也可能剛剛連線失敗
            nxt = next_scheduled(scheduled)
            if nxt is None:
                return None
            when, task = nxt
            if not self._sleep_until(when, task):
                return None
            if self._injected:
                task = self._injected.pop(0)       # 被叫醒：先跑加入的那個
            if self._connect_with_retry(dev, task):
                return task
            self._task(task.name, "error", "連線失敗")
        return None

    def _connect_with_retry(self, dev: Device, task: TaskConfig) -> bool:
        """到點時重新連線，連不上就隔 CONNECT_RETRY_DELAY 秒再試，全部失敗才放掉這一格。"""
        for attempt in range(1, CONNECT_RETRIES + 2):
            self._status("重新連線")
            try:
                dev.connect()
                return True
            except AdbError as e:
                if attempt > CONNECT_RETRIES:
                    log.error("連線失敗，「%s」這一輪跳過：%s", self._title(task), e)
                    return False
                log.warning("連線失敗，%d 秒後重試（第 %d 次，最多 %d 次）：%s",
                            CONNECT_RETRY_DELAY, attempt, CONNECT_RETRIES,
                            str(e).strip().splitlines()[0])
                self._status(f"連線失敗，等候重試（第 {attempt} 次）")
                if self.stop_event.wait(CONNECT_RETRY_DELAY):
                    return False
        return False

    def _passed_during(
        self, start: datetime, end: datetime, current: TaskConfig | None = None
    ) -> list[TaskConfig]:
        """上一輪執行期間經過的排定時刻，依時刻排序。

        ⚠ 判斷落在執行區間內，不是今天已過，否則會永遠補跑。
        ⚠ 起點退到整分鐘：`start` 比排定時刻晚幾百毫秒，同一分鐘的腳本會落在區間外。
        ⚠ 排除剛跑完的腳本自己那一格：它就是被那一格叫起來的。
        """
        base = start.replace(second=0, microsecond=0)
        found: list[tuple[datetime, TaskConfig]] = []
        for task in self.tasks:
            # 跨午夜的執行要兩天都看
            for day in {start.date(), end.date()}:
                for hh, mm in task.times_on(day):
                    when = datetime.combine(day, datetime.min.time()).replace(
                        hour=hh, minute=mm)
                    if not (base <= when <= end):
                        continue
                    if task is current and when <= start:
                        continue        # 它就是被這一格叫起來的
                    found.append((when, task))
        return [task for _, task in sorted(found, key=lambda pair: pair[0])]

    def _task(self, name: str, state: str, note: str) -> None:
        if self.task_hook is not None:
            try:
                self.task_hook(name, state, note)
            except Exception:
                pass

    def _status(self, text: str) -> None:
        if self.status_hook is not None:
            try:
                self.status_hook(text)
            except Exception:
                pass

    def _sleep_until(self, when: datetime, task: TaskConfig) -> bool:
        """睡到排定時刻，回傳是否睡完（False 代表被要求停止）。每秒醒一次更新倒數。"""
        log.info("下一輪「%s」排在 %s（%s後）%s", self._title(task),
                 when.strftime("%m/%d %H:%M"),
                 _pretty_wait((when - datetime.now()).total_seconds()),
                 "，按 Ctrl + C 可結束" if self.interactive else "")
        self.waiting = True
        shown = ""
        try:
            while True:
                remain = (when - datetime.now()).total_seconds()
                if remain <= 0 or self._injected:
                    return True
                # 文字有變才更新，避免重畫介面。
                text = (f"等候下一輪「{self._title(task)}」　"
                        f"{when.strftime('%m/%d %H:%M')} 開始，"
                        f"還有 {_pretty_wait(remain)}")
                if text != shown:
                    self._status(text)
                    shown = text
                if self.stop_event.wait(min(remain, 1.0)):
                    return False
        finally:
            self.waiting = False

    def describe_setup(self) -> None:
        """開場印出這次執行的設定：版本、設定檔、裝置、資源、排程、開關。

        ⚠ 要排在建立引擎之前：引擎的「略過規則」訊息接在這段後面。
        """
        cfg, tasks = self.cfg, self.tasks
        log.info("═══ 杖劍傳說助手 v%s ═══", VERSION)
        log.info("設定檔　：%s", cfg.path)
        log.info("目標裝置：%s（預期 %dx%d、%d dpi）", cfg.device.target,
                 cfg.device.width, cfg.device.height, cfg.device.dpi)
        log.info("可用資源：模板 %d 張、腳本 %d 份",
                 len(resource_files("templates", "*.png")),
                 len(resource_files("scripts", "*.yaml")))

        if self.one_shot:
            log.info("執行方式：只跑「%s」一輪，不進入排程", self._title(tasks[0]))
        else:
            log.info("執行方式：依排程輪流執行，啟動時先跑「%s」",
                     self._title(tasks[0]))
            # ⚠ 子項目用「・」起頭：紀錄面板是比例字型，全形空格對不齊。
            for task in tasks:
                log.info("・%s ── %s，%s", self._title(task), task.describe(),
                         f"完成 {task.repeat} 次就換下一個腳本" if task.repeat
                         else "次數不限，由腳本判斷何時結束")
            if not any(t.times or t.weekly for t in tasks):
                log.info("・沒有任何腳本設定執行時間，這一輪跑完就結束")

        on = [k for k, v in cfg.options.items() if v is True]
        off = [k for k, v in cfg.options.items() if v is False]
        other = [f"{k} = {v}" for k, v in cfg.options.items()
                 if not isinstance(v, bool)]
        log.info("已開啟　：%s", "、".join(on) or "（無）")
        if off:
            log.info("已關閉　：%s", "、".join(off))
        if other:
            log.info("其他設定：%s", "、".join(other))
        log.info("══════════════════════════")
