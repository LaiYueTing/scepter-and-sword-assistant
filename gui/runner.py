"""在背景執行緒跑排程，把狀態回報給介面。

排程本身在 `core/runner.py`，命令列與介面共用同一份；這裡只負責「另開一條
執行緒」與「怎麼叫停」（`threading.Event`）。
"""

from __future__ import annotations

import threading

from core.config import Config, TaskConfig
from core.runner import Runner
from .bridge import Channel


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
        try:
            self.runner.run()
        except Exception as e:
            # 連不上裝置、腳本讀不到都會走到這裡。訊息本身已經是給人看的中文。
            self.channel.send("failed", str(e))
        finally:
            self.channel.send("running", False)

    def request_stop(self) -> None:
        """要求結束。引擎會在一個 tick 內醒來，收尾動作照常跑完。"""
        self.stop_event.set()
