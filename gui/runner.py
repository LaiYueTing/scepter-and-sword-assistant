"""在背景執行緒跑排程，把狀態回報給介面。

排程本身在 `core/runner.py`，命令列與介面共用同一份；這裡只負責「另開一條
執行緒」與「怎麼叫停」（`threading.Event`）。
"""

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
            # 連不上裝置、腳本讀不到都會走到這裡。訊息本身已經是給人看的中文。
            #
            # ⚠ **一定要寫進紀錄。** 只送 `failed` 事件的話，那句話只在狀態列閃
            #   一下就被蓋掉——實機跑起來之後能看到的只有紀錄，排程死掉卻不留
            #   痕跡是最糟的形狀。
            log.exception("排程結束於未預期的錯誤：%s", e)
            error = str(e)
        self.channel.send("running", False)
        # ⚠ **順序不能反。** 介面收到 `running=False` 會把狀態列寫回「待命中」，
        #   所以先送 `failed` 的那句話活不過幾毫秒——實測使用者的畫面上是
        #   「待命中」，任務卡卻還停在「執行中」，完全看不出出過事。
        if error:
            self.channel.send("failed", error)

    def request_stop(self) -> None:
        """要求結束。引擎會在一個 tick 內醒來，收尾動作照常跑完。"""
        self.stop_event.set()
