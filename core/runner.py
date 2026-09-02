"""排程執行：依設定輪流跑啟用的腳本。

流程是「啟動先跑一輪 → 跑完找最近的下一個時刻 → 休眠 → 重新連線」。
CLI 與 GUI 共用這一份，停止改吃 `threading.Event`（GUI 沒有 Ctrl+C 可送）。
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


def next_scheduled(
    tasks: list[TaskConfig], now: datetime | None = None
) -> tuple[datetime, TaskConfig] | None:
    """在所有腳本中挑出最近的下一個 (時刻, 腳本)。沒有任何排程就回 None。

    `now` 可以指定，方便測試不同時間點會排到哪一個腳本。
    """
    best = None
    for task in tasks:
        when = task.next_run(now)
        if when and (best is None or when < best[0]):
            best = (when, task)
    return best


def _pretty_wait(seconds: float) -> str:
    """把等待時間寫成好讀的形式。排程動輒好幾小時，秒數看了沒感覺。"""
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
        # 腳本內部名稱（dungeon）→ 中文名（自動副本）。讀進腳本之後才填得起來，
        # 在那之前寫紀錄就退回內部名稱。
        self._titles: dict[str, str] = {}
        self.status_hook = status_hook
        # (腳本名, 狀態, 說明)。介面用它更新任務卡，命令列不接這個。
        self.task_hook = task_hook
        # 終端機才提示 Ctrl+C——GUI 沒有那個鍵可按，寫了只會讓人去按而沒反應
        self.interactive = interactive

    # ---------- 對外 ----------

    def stop(self) -> None:
        """要求結束。等待中的引擎會在一個 tick 內醒來，收尾照常執行。"""
        self.stop_event.set()

    def run(self) -> int:
        """依排程輪流執行，回傳結束碼。腳本讀不到會拋 ScriptError。"""
        # ⚠ 先讀腳本再印設定說明：說明要寫出中文名（腳本的 `name:`），讀進來才知道。
        #   讀不到時仍然先把設定印完再拋，那幾行是查「為什麼讀不到」的起點。
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

        # 每個腳本一個引擎，各自保有自己的規則狀態（觸發次數、sustain 計時），
        # 所以要留著重複使用，不能每輪重建。
        engines: dict[str, Engine] = {}
        scheduled = [t for t in self.tasks if t.times or t.weekly]

        # 待辦佇列：啟動時先跑清單第一個，後面接今天已過而不會再輪到的那幾格
        # （見 _missed_today）。真正決定「這一輪跑誰」的是 _take_next()。
        queue: list[TaskConfig] = [self.tasks[0]]
        if self.cfg.runtime.catch_up:
            queue += [t for t in self._missed_today() if t is not queue[0]]
            if len(queue) > 1:
                log.info("補跑今天已過排定時刻的腳本：%s",
                         "、".join(self._title(t) for t in queue[1:]))
        current: TaskConfig | None = None
        try:
            while not self.stop_event.is_set():
                if current is None:
                    current = self._take_next(dev, queue, scheduled)
                    if current is None:
                        break
                script = scripts[current.name]
                log.info("───── 執行「%s」，目標次數：%s ─────",
                         script.name, current.repeat or "不限")

                engine = engines.get(current.name)
                if engine is None:
                    # ⚠ 輪到這個腳本才建立引擎：建立時會報告「哪些規則因設定而不
                    #   啟用」，要排在分隔線之後才看得出那是哪個腳本的規則。
                    engine = engines[current.name] = Engine(
                        dev, script, repeat=current.repeat, dry_run=self.dry_run,
                        stop_event=self.stop_event, status_hook=self.status_hook)
                else:
                    engine.reset()   # 同一個腳本再跑一輪，清掉上一輪的規則狀態
                self._task(current.name, "running", "執行中")
                started = datetime.now()
                # ⚠ 先算好「下一個排定時刻」再交給引擎，讓它到點自己讓位。少了這個，
                #   永不收工的腳本（不領獎 ＋ 次數用完不收工 ＋ 次數不限）會把整個
                #   排程擋住，而紀錄上看起來一切正常。
                #
                # ⚠ 補跑期間也要帶上限，否則會一路輾過排定時刻。讓位之後那一格
                #   由 _passed_during() 接住並排到佇列最前面。
                nxt = next_scheduled(scheduled)
                failed = ""
                try:
                    engine.run(until=nxt[0] if nxt else None)
                except AdbError as e:
                    # ⚠ 一輪跑到一半斷線（模擬器被關掉、網路斷了）不該讓整個排程
                    #   結束，否則當天剩下的腳本全部不會執行。這一輪放掉，
                    #   下一個排定時刻再試。
                    log.error("執行「%s」時中斷：%s", script.name, e)
                    failed = "連線中斷"
                    if self.one_shot:
                        raise
                except Exception as e:
                    # ⚠ **沒預料到的例外也只能放掉這一輪**，理由和上面相同。少了
                    #   這一段，一輪炸掉會把當天剩下的腳本全部帶走，而紀錄上只有
                    #   一段空白。
                    # ⚠ 一定要用 log.exception。訊息本身多半看不出是哪裡壞的，而
                    #   這種例外照定義就是我們沒想到的那一種，traceback 是唯一線索。
                    log.exception("執行「%s」時發生未預期的錯誤：%s", script.name, e)
                    failed = "執行時發生錯誤"
                    if self.one_shot:
                        raise
                spent = int((datetime.now() - started).total_seconds())
                # ⚠ 不要寫「剛才完成」。這句會一直掛在卡片上到下一輪為止，
                #   而下一輪可能是好幾個小時以後——那時「剛才」已經不成立了。
                #   卡片的徽章講的是**現在是什麼狀態**，不是「剛剛發生什麼」。
                took = logger.pretty_seconds(spent)
                # ⚠ **出錯的那一輪不能寫成「這一輪沒有完成」。** 那句話和「次數
                #   用盡就收工」長得一模一樣，卡片也會從紅色變回一般色——出過事
                #   在畫面上就完全看不出來了。
                if failed:
                    self._task(current.name, "error", f"{failed}（{took}）")
                else:
                    self._task(current.name, "done",
                               f"已完成 {engine.completed} 次（{took}）"
                               if engine.completed
                               else f"這一輪沒有完成（{took}）")

                if self.one_shot or self.stop_event.is_set():
                    break

                # 執行期間經過的排定時刻要補回來（見 _passed_during）。
                # ⚠ 插在佇列**最前面**：那是剛剛才過去的時刻，比早上就錯過的
                #   那幾格急。
                if self.cfg.runtime.catch_up:
                    late = [t for t in self._passed_during(
                                started, datetime.now(), current)
                            if t not in queue]
                    if late:
                        log.info("執行期間經過了「%s」的排定時刻，接著補跑",
                                 "」「".join(self._title(t) for t in late))
                        queue[:0] = late

                # 剛剛是「讓位」而不是自己收工，代表該做的還沒做完——排回去，
                # 等這一波排定時刻與補跑清完再接著跑。
                #
                # ⚠ 少了這一段，讓位一次就等於整天只做一半：次數還有、獎勵還沒領
                #   的腳本再也沒有人叫它回來，而紀錄上每一行都正常。
                # ⚠ 排在**最後面**：剛過去的那幾格（late）比它急，而它本來就是
                #   被判定成「可以晚一點」才讓位的。
                # ⚠ 不會無限讓位：until 一定是未來的時刻，所以重跑之後至少要再
                #   完成一次（count）才可能再讓一次，每一輪都有進展。
                if (self.cfg.runtime.catch_up and engine.yielded
                        and current not in queue):
                    log.info("「%s」還沒做完就讓位了，排到後面接著跑",
                             self._title(current))
                    queue.append(current)

                current = None      # 下一輪跑誰交給 _take_next 決定
        except KeyboardInterrupt:
            log.info("使用者中斷，結束排程")

        self._status("已停止")
        return 0

    # ---------- 內部 ----------

    def _title(self, task: TaskConfig) -> str:
        """腳本的中文名稱，讀不到就退回內部名稱。

        紀錄不該露出 dungeon / raid 這種設定檔的鍵。中文名直接取自腳本的
        `name:`，不另外維護一份對照表。
        """
        return self._titles.get(task.name, task.name)

    def _missed_today(self, now: datetime | None = None) -> list[TaskConfig]:
        """今天已經過了排定時刻、而且今天不會再輪到的腳本，依原本的時刻排序。

        目的是「不要讓今天整個跳過」（晚上才開程式，08:00 與 09:30 都會被算到
        明天去）。刻意不記錄「今天跑過沒」——狀態檔會和實際情況不一致，而腳本
        本來就會進遊戲自己確認，補跑一輪只是進去看一眼就收工。

        ⚠ 今天還輪得到的不補跑。一天跑兩次的腳本只要還有下一格，今天本來就跑
          得到，提前補一輪只是把那一格的有限次數挪到更早用掉。

        ⚠ 腳本自己也可以退出補跑（`TaskConfig.catch_up = false`）。討伐就是這種
          ——補跑的前提是「晚一點做也一樣」，而它的價值就綁在那個時刻上。
        """
        now = now or datetime.now()
        clock = (now.hour, now.minute)
        found: list[tuple[tuple[int, int], TaskConfig]] = []
        for task in self.tasks:
            # ⚠ 要問「今天」會跑哪些時刻，不能直接看 times：每週一的競技場在
            #   星期三並不算「今天錯過的」，拿 times 去比會每天都想補跑一次。
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
        """下一個排定時刻是不是近在眼前。夠近就回傳 (時刻, 腳本)，否則 None。

        給「補跑要不要讓路」用的。補跑晚一點做沒差，而排定時刻是使用者指定的
        那一刻（討伐 21:00 的價值就在人最多），所以時刻優先。

        ⚠ `catch_up_guard_minutes` 設 0 就整個關掉（補跑照舊搶先）。
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
        """決定這一輪跑誰：排定時刻優先，其次才是待補跑的。回 None 代表結束。

        ⚠ 啟動那一輪也要讓路。它本質上和補跑是同一件事（都是「不等時刻、先做
          點什麼」）。
        ⚠ 不比對「近的那個是不是佇列第一個」。就算是同一個腳本，等到時刻再跑
          也比較好——現在跑的話跑完時刻還沒到，等一下會被排程再叫一次。
        ⚠ `--once` 不讓路。那是人在旁邊手動叫的，乾等十幾分鐘會像當住了。
        """
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
        """睡到下一個排定時刻並重新連線，回傳該跑的腳本。

        沒有排程、或中途被要求停止就回 None。

        ⚠ 連不上不能讓整個排程結束——模擬器只是還沒開機或網路剛好斷了的話，
          當天剩下的腳本會全部不執行。連不上就放掉這一格，繼續等下一個時刻
          （那時 `next_scheduled()` 算的已經是更後面的時刻，不會忙碌重試）。
        """
        while not self.stop_event.is_set():
            # 每次都重新算：腳本可能跑了好幾個小時，也可能剛剛連線失敗
            nxt = next_scheduled(scheduled)
            if nxt is None:
                return None
            when, task = nxt
            if not self._sleep_until(when, task):
                return None
            self._status("重新連線")
            try:
                dev.connect()
            except AdbError as e:
                log.error("連線失敗，「%s」這一輪跳過：%s", self._title(task), e)
                self._task(task.name, "error", "連線失敗")
                continue
            return task
        return None

    def _passed_during(
        self, start: datetime, end: datetime, current: TaskConfig | None = None
    ) -> list[TaskConfig]:
        """在上一輪執行期間經過的排定時刻，依時刻排序。

        `next_scheduled()` 只看未來，所以某個腳本正在跑的時候，別的腳本的時刻
        就這樣過去了——那一格今天等於沒發生，而且完全沒有紀錄。

        ⚠ 判斷的是「落在這一輪的執行區間內」，不是「今天已過」。後者會讓每跑完
          一輪就把今天所有跑過的腳本再補一次，永遠停不下來。

        ⚠ **起點要退到整分鐘。** `start` 是 `datetime.now()`，取得的時間點在
          引擎建好之後（實測 08:00:00.213），而排定時刻是 08:00:00.000。直接比
          的話，**和這一輪排在同一分鐘的腳本永遠差 0.2 秒落在區間外**，那一格
          整個消失而且沒有任何紀錄。

        ⚠ 退到整分鐘之後要把**剛跑完的那個腳本自己的那一格**排除掉：它就是被那
          一格叫起來的，不是「錯過」。少了這個判斷，清單第一個腳本每天都會多跑
          一輪（它自己的起跑時刻永遠落在自己的執行區間內）。
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
        """睡到排定時刻，回傳「是否睡完了」（False 代表中途被要求停止）。

        每秒醒一次，讓狀態顯示跟著倒數、也讓停止即時生效。
        """
        log.info("下一輪「%s」排在 %s（%s後）%s", self._title(task),
                 when.strftime("%m/%d %H:%M"),
                 _pretty_wait((when - datetime.now()).total_seconds()),
                 "，按 Ctrl + C 可結束" if self.interactive else "")
        while True:
            remain = (when - datetime.now()).total_seconds()
            if remain <= 0:
                return True
            self._status(f"等候下一輪「{self._title(task)}」　"
                         f"{when.strftime('%m/%d %H:%M')} 開始，"
                         f"還有 {_pretty_wait(remain)}")
            if self.stop_event.wait(min(remain, 1.0)):
                return False

    def describe_setup(self) -> None:
        """開場印出「這一次是用什麼設定在跑」：版本、設定檔、裝置、資源、排程、開關。

        ⚠ 要排在建立引擎之前。引擎初始化時會報告「哪些規則因設定而不啟用」，
          那是這段說明的延伸，順序顛倒就變成先看到結論再看到前提。
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
            # ⚠ 子項目用「・」起頭，不要用全形空格縮排。那是等寬終端機的排版思維，
            #   而紀錄面板是比例字型，補出來的空白只會歪成一格突兀的空隙。
            for task in tasks:
                log.info("・%s ── %s，完成 %s 次就換手",
                         self._title(task), task.describe(), task.repeat or "不限")
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
