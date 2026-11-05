"""在背景執行緒跑排程（core/runner.py），把狀態回報給介面。"""

from __future__ import annotations

import threading

from core import logger
from core.config import Config, TaskConfig
from core.runner import Runner
from .bridge import Channel

log = logger.get("main")


class RunnerThread(threading.Thread):
    def __init__(
        self,
        cfg: Config,
        tasks: list[TaskConfig],
        channel: Channel,
        one_shot: bool = False,
    ):
        super().__init__(daemon=True)
        self.channel = channel
        self.stop_event = threading.Event()
        self.runner = Runner(
            cfg, tasks, one_shot=one_shot,
            stop_event=self.stop_event,
            # 狀態列的一句話
            status_hook=lambda text: channel.send("status", text),
            # 任務卡要指名是哪一個腳本，所以和 status 分開
            task_hook=lambda name, state, note: channel.send(
                "task", {"name": name, "state": state, "note": note}),
        )

    def run(self) -> None:
        error = ""
        try:
            self.runner.run()
        except Exception as e:
            # 連不上裝置、腳本讀不到都走到這裡。⚠ 一定要寫進紀錄，狀態列的訊息會被蓋掉。
            log.exception("排程結束於未預期的錯誤：%s", e)
            error = str(e)
        self.channel.send("running", False)
        # ⚠ 順序不可反：`running=False` 會把狀態列寫回「待命中」，`failed` 要排在後面。
        if error:
            self.channel.send("failed", error)

    def request_stop(self) -> None:
        """要求結束。引擎會在一個 tick 內醒來，結束程序照常跑完。"""
        self.stop_event.set()
