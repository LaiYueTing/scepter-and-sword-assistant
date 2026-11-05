"""前端呼叫的方法表，一個方法一件事。

⚠ 耗時的操作（adb connect、探索、更新下載）先回傳，做完再推事件。
⚠ 執行中不能改設定：引擎在建立時才套用開關。
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import webbrowser
from datetime import date
from pathlib import Path
from typing import Any

from core import confedit, dailystate, logger, optionmeta, uistate
from core.config import (ROOT, VERSION, WEEKDAY_NAMES, Config, TaskConfig,
                         resource_file)
from .bridge import Channel

log = logger.get("gui")

# 關視窗時等待結束程序的上限（秒）。
CLOSE_TIMEOUT = 30


def _open_in_shell(path: Path) -> None:
    """用系統預設程式開啟檔案或資料夾。⚠ 不用 `webbrowser.open`：資料夾可能被開到瀏覽器。"""
    try:
        os.startfile(str(path))                     # type: ignore[attr-defined]
    except AttributeError:                          # 非 Windows
        subprocess.run(["xdg-open", str(path)], check=False)


class Api:
    """方法表。每個公開方法就是一個前端呼叫得到的方法。

    ⚠ 公開成員必須全部是方法：pywebview 會走訪公開成員。
    """

    def __init__(self, channel: Channel):
        self._channel = channel
        # ⚠ 底線開頭，pywebview 不會走訪。
        self._cfg: Config | None = None
        self._runner = None
        self._discovering = False
        self._updating = False
        self._release = None            # 查到的新版，等使用者決定要不要裝
        self._window = None             # 由 attach_window 設定
        # 視窗縮到系統匣之後的通知掛鉤
        self._on_hidden = None
        self._on_painted = None

    # ================= 設定 =================

    def state(self, _: dict) -> dict:
        """介面啟動時需要的全部資料。"""
        cfg = self._cfg = Config.load()
        return {
            "version": VERSION,
            "config_path": str(cfg.path),
            "log_dir": str(ROOT / "logs"),
            "is_new": cfg.is_new,
            "frozen": bool(getattr(sys, "frozen", False)),
            "device": {
                "serial": cfg.device.serial or "",
                "host": cfg.device.host,
                "port": cfg.device.port,
                "spec": f"{cfg.device.width}x{cfg.device.height} / {cfg.device.dpi}dpi",
            },
            "tasks": [self._task_json(t) for t in cfg.tasks],
            "options": self._options_json(cfg),
            "running": self.is_running(),
        }

    @staticmethod
    def _task_json(t: TaskConfig) -> dict:
        nxt = t.next_run()
        return {
            "name": t.name,
            # 中文名取自腳本的 `name:`
            "title": optionmeta.task_label(t.name),
            "enabled": t.enabled,
            "repeat": t.repeat,
            "repeat_hint": optionmeta.REPEAT_HINTS.get(t.name, ""),
            # 每週與每日是兩個不同的鍵，模式由後端決定。⚠ 兩種都有時算每日。
            "mode": "weekly" if t.weekly and not t.times else "daily",
            "daily_at": [f"{h:02d}:{m:02d}" for h, m in t.times],
            "weekly_at": [f"{WEEKDAY_NAMES[d]} {h:02d}:{m:02d}"
                          for d, h, m in t.weekly],
            "schedule": t.describe(),
            "catch_up": t.catch_up,
            "next_run": nxt.isoformat() if nxt else "",
        }

    @staticmethod
    def _template_options() -> dict[str, Any]:
        """設定範本裡的預設值，補上舊設定檔缺少的鍵。

        ⚠ 範本的值和腳本的 `${鍵:預設}` 是同一組（`tests/test_options_complete.py`）。
        """
        try:
            import yaml
            raw = yaml.safe_load(
                resource_file(".", "config.example.yaml").read_text(encoding="utf-8"))
            return dict((raw or {}).get("options") or {})
        except Exception as e:
            log.warning("讀不到設定範本的預設值：%s", e)
            return {}

    @staticmethod
    def _options_json(cfg: Config) -> dict:
        """開關與數值，附上標籤、說明、範圍與所屬腳本。對照表在 `core/optionmeta.py`。"""
        # 範本補底、使用者的設定覆蓋，順序照範本。
        merged = {**Api._template_options(), **cfg.options}

        items: dict[str, dict] = {}
        for key, value in merged.items():
            label, hint = optionmeta.OPTION_LABELS.get(key, (key, ""))
            # ⚠ 數值（`buy_counts`、`raid_join_players`）不可畫成核取方塊。
            entry: dict[str, Any] = {
                "value": value, "label": label, "hint": hint,
                # 是否為上一個開關的子項目，縮排由介面處理。
                "sub": key in optionmeta.SUB_OPTIONS,
            }
            if isinstance(value, bool):
                entry["kind"] = "bool"
            else:
                lo, hi, suffix, decimals = optionmeta.OPTION_RANGES.get(
                    key, (0, 99, "", 0))
                # ⚠ 小數位不可省略：raid_plateau_players 預設 6.5。
                entry.update(kind="number", min=lo, max=hi, suffix=suffix,
                             decimals=decimals, step=0.5 if decimals else 1)
            items[key] = entry

        grouped = {k for _, keys in optionmeta.OPTION_GROUPS for k in keys}
        groups = [
            {"name": name, "title": optionmeta.task_label(name),
             "keys": [k for k in keys if k in items]}
            for name, keys in optionmeta.OPTION_GROUPS
        ]
        rest = [k for k in items if k not in grouped]
        if rest:
            groups.append({"name": "_other", "title": "其他", "keys": rest})
        return {"items": items, "groups": groups}

    def save(self, params: dict) -> dict:
        """就地改寫 config.yaml，走 `core/confedit.py` 以保留註解。"""
        if self.is_running():
            raise RuntimeError("執行中不能改設定")
        changes = params.get("changes") or []
        edits = {tuple(c["path"]): c["value"] for c in changes}
        if not edits:
            return {"changed": 0}
        confedit.save(self._cfg.path, edits)
        self._cfg = Config.load()
        log.info("設定已更新（%d 項）", len(edits))
        return {"changed": len(edits)}

    def reveal(self, params: dict) -> dict:
        """用系統預設程式開啟設定檔或紀錄資料夾。"""
        what = params.get("what")
        _open_in_shell(self._cfg.path if what == "config" else ROOT / "logs")
        return {}

    # ---- 內建的設定檔編輯器（介面沒有的設定：adb、runtime、腳本清單）----

    def config_read(self, _: dict) -> dict:
        """讀出 config.yaml 的原文。"""
        path = self._cfg.path
        raw = path.read_bytes()
        return {"path": str(path), "text": raw.decode("utf-8")}

    def config_write(self, params: dict) -> dict:
        """把編輯器裡的原文寫回 config.yaml。

        ⚠ 先寫到旁邊、用 `Config.load()` 驗過才換上去；驗不過時原檔不變。
        ⚠ 換行沿用原檔。
        """
        if self.is_running():
            raise RuntimeError("執行中不能改設定")
        text = params.get("text")
        if not isinstance(text, str) or not text.strip():
            raise RuntimeError("內容是空的，沒有寫入")

        path = self._cfg.path
        crlf = b"\r\n" in path.read_bytes()
        body = text.replace("\r\n", "\n")
        tmp = path.with_suffix(path.suffix + ".check")
        try:
            with open(tmp, "w", encoding="utf-8",
                      newline="\r\n" if crlf else "\n") as f:
                f.write(body)
            Config.load(tmp)
        except Exception as e:
            # 訊息先說明檔案沒有寫入，再附 PyYAML 的英文訊息。
            raise RuntimeError(
                "設定檔沒有寫入，因為這份內容載不起來：" + chr(10) + str(e)) from None
        else:
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)

        self._cfg = Config.load()
        log.info("設定檔已由內建編輯器整份寫回")
        return {}

    # ================= 當日計數（state.json，見 core/dailystate.py）=================

    def daily_state(self, _: dict) -> dict:
        """今天各項的計數與上限。"""
        from core.engine import Script, ScriptError   # 延後載入 cv2

        cfg = self._cfg or Config.load()
        done = dailystate.counts()
        rows, seen = [], set()
        for task in cfg.tasks:
            try:
                script = Script.load(task.name, cfg.options)
            except (ScriptError, OSError):
                continue        # 腳本錯誤由「開始執行」回報
            title = optionmeta.task_label(task.name)
            for rule in script.rules:
                if rule.max_fires_daily:
                    key = f"{task.name}/{rule.name}"
                    if key in seen:
                        continue
                    seen.add(key)
                    rows.append({
                        "key": key,
                        "task": title,
                        # 取「→」後面那半：被計數的是動作。
                        "label": rule.name.split("→")[-1].strip(),
                        "done": done.get(key, 0),
                        "limit": rule.max_fires_daily,
                        "stale": False,
                    })
                # `tally` 沒有上限，名稱由腳本給，多條規則共用一格時要去重。
                for action in rule.actions:
                    label = action.get("tally")
                    if not label:
                        continue
                    key = f"{task.name}/{label}"
                    if key in seen:
                        continue
                    seen.add(key)
                    rows.append({"key": key, "task": title, "label": label,
                                 "done": done.get(key, 0), "limit": 0,
                                 "stale": False})
        # 狀態檔裡有、但現在的腳本沒有的鍵（改過規則名、關閉的開關），也要列出來。
        for key, value in done.items():
            if key not in seen:
                task, _, name = key.partition("/")
                rows.append({
                    "key": key,
                    "task": optionmeta.task_label(task) or task,
                    "label": name.split("→")[-1].strip(),
                    "done": value,
                    "limit": 0,
                    "stale": True,
                })
        return {"date": date.today().isoformat(), "rows": rows,
                "path": str(dailystate.PATH)}

    def daily_reset(self, params: dict) -> dict:
        """把某一項（或全部）今天的計數歸零。⚠ 執行中不可用：引擎在建立時就讀入計數。"""
        if self.is_running():
            raise RuntimeError("執行中不能重設當日計數，請先停止")
        key = params.get("key") or None
        dailystate.reset(key)
        log.info("已重設當日計數：%s", key or "全部")
        return self.daily_state({})

    # ================= 執行 =================

    def is_running(self) -> bool:
        return self._runner is not None and self._runner.is_alive()

    def running(self, _: dict) -> dict:
        return {"running": self.is_running()}

    def start(self, params: dict) -> dict:
        if self.is_running():
            raise RuntimeError("已經在執行了")
        cfg = self._cfg = Config.load()
        only = str(params.get("only") or "")
        tasks = [cfg.task_of(only)] if only else cfg.enabled_tasks
        if not tasks:
            raise RuntimeError("沒有啟用任何腳本")

        from .runner import RunnerThread          # 延後載入 cv2
        self._runner = RunnerThread(
            cfg, tasks, self._channel, one_shot=bool(params.get("once")))
        self._runner.start()
        self._channel.send("running", True)
        return {}

    def run_now(self, params: dict) -> dict:
        """讓一份不排程的腳本（虛空裂縫）現在跑一輪。回傳 `now`：True 表示馬上開始。

          沒在執行     → 開一個只跑這一輪的排程
          排程等待中   → 叫醒它先跑這個，跑完回去等下一個時刻
          正在跑別的   → 接在那一輪後面

        ⚠ 結束程序執行中不接受：停止要求已送出，這一輪不會被執行。
        """
        name = str(params.get("task") or "")
        if not name:
            raise RuntimeError("沒有指定要跑的腳本")
        if self.is_running():
            if self._runner.stop_event.is_set():
                raise RuntimeError("正在停止中，等它結束再按")
            cfg = self._cfg or Config.load()
            return {"now": self._runner.runner.inject(cfg.task_of(name))}
        self.start({"only": name, "once": True})
        return {"now": True}

    def run_cancel(self, params: dict) -> dict:
        """中斷 run_now 加入的那一份，排程照常。執行中的立刻結束、不跑結束程序；排隊中的移除。"""
        name = str(params.get("task") or "")
        if not name or not self.is_running():
            return {"cancelled": False}
        cancelled = self._runner.runner.abort(name)
        if cancelled:
            log.info("使用者中斷了「%s」", optionmeta.task_label(name))
        return {"cancelled": cancelled}

    def stop(self, _: dict) -> dict:
        if not self.is_running():
            raise RuntimeError("沒有在執行")
        self._runner.request_stop()
        # ⚠ 結束程序的等待不可中斷，這裡不等它。引擎會逐步回報「結束程序執行中　第 N 步」。
        self._channel.send("status", "停止中，正在執行結束程序 ⋯")
        return {}

    def join(self, params: dict) -> dict:
        """等結束程序跑完，關視窗時使用，逾時就放棄。"""
        if self.is_running():
            self._runner.join(timeout=float(params.get("timeout") or 30))
        return {"running": self.is_running()}

    # ================= 裝置 =================

    def test(self, _: dict) -> dict:
        """測試連線，開執行緒做，結果用事件推回去。"""
        def work():
            from core.adb import Device
            try:
                dev = Device(Config.load())
                dev.connect()
                self._channel.send("tested", {
                    "ok": True,
                    "text": f"連線正常：{dev.cfg.device.target}",
                })
            except Exception as e:
                # AdbError 的訊息本身就是檢查清單
                self._channel.send("tested", {"ok": False, "text": str(e)})

        threading.Thread(target=work, daemon=True).start()
        return {}

    def discover(self, params: dict) -> dict:
        """探索可用的模擬器，開執行緒做。`auto` 表示開視窗時自動觸發。

        ⚠ 自動觸發不做多埠掃描（`deep=False`），見 core/discover.py。
        """
        if self._discovering:
            raise RuntimeError("正在探索中")
        self._discovering = True

        def work():
            from core import discover
            from core.adb import Device
            try:
                # ⚠ 不呼叫 dev.connect()：連不上會丟例外，探索就中斷了。
                found = discover.scan(Device(self._cfg),
                                      deep=not params.get("auto"))
                d = self._cfg.device
                want_size, want_dpi = f"{d.width}x{d.height}", d.dpi
                self._channel.send("discovered", {
                    "ok": True,
                    "items": [self._found_json(f, want_size, want_dpi)
                              for f in found],
                })
                log.info("探索到 %d 台裝置", len(found))
            except Exception as e:
                self._channel.send("discovered", {"ok": False, "error": str(e)})
            finally:
                self._discovering = False

        threading.Thread(target=work, daemon=True).start()
        return {}

    @staticmethod
    def _found_json(f, want_size: str, want_dpi: int) -> dict:
        host, _, port = f.serial.rpartition(":")
        return {
            "serial": f.serial,
            "host": host,
            "port": int(port) if port.isdigit() else 0,
            # 旗標排最前面
            "label": f.label(want_size, want_dpi),
            # 多行版給 tooltip
            "detail": f.detail(want_size, want_dpi),
            "usable": f.is_usable,
            # 規格不符時直接標出來
            "ok_size": f.matches_spec(want_size, want_dpi),
        }

    # ================= 更新 =================

    def update_check(self, params: dict) -> dict:
        """查有沒有新版。自動查詢失敗時不出聲。⚠ 回報要分得出「已經是最新」與「查不到」。"""
        def work():
            from core import updater
            try:
                rel, err = updater.check_status()
            except Exception as e:
                rel, err = None, str(e)
            self._release = rel
            can, why = updater.can_apply()
            self._channel.send("update", {
                "found": rel is not None,
                "version": rel.version if rel else "",
                "notes": rel.notes if rel else "",
                "size_text": rel.size_text if rel else "",
                "page": updater.PAGE,
                "can_apply": can,
                "why": why,
                # 空字串表示查詢成功，有值就是查不到的原因。
                "error": err,
                # 自動查詢不跳對話框
                "quiet": bool(params.get("quiet")),
            })

        threading.Thread(target=work, daemon=True).start()
        return {}

    def update_apply(self, _: dict) -> dict:
        """下載並換檔。⚠ 執行中不可更新：重新啟動會中斷戰鬥。"""
        if self.is_running():
            raise RuntimeError("執行中不能更新，請先停止")
        if self._release is None:
            raise RuntimeError("沒有可安裝的更新")
        if self._updating:
            raise RuntimeError("正在更新中")
        self._updating = True

        def work():
            from core import updater
            rel = self._release
            try:
                def on_progress(done: int, total: int) -> None:
                    # ⚠ 只推事件，不寫紀錄。
                    self._channel.send("update_progress",
                                      {"done": done, "total": total})

                path = updater.download(rel, on_progress)
                if path is None:
                    raise RuntimeError("下載失敗，請稍後再試或到發布頁手動下載")
                ok, why = updater.apply(path)
                if not ok:
                    raise RuntimeError(why)
                # ⚠ 不在這裡 restart()，由使用者選擇後的 update_restart() 觸發。
                self._channel.send("update_done",
                                  {"ok": True, "version": rel.version})
            except Exception as e:
                log.warning("更新失敗：%s", e)
                self._channel.send("update_done", {"ok": False, "error": str(e)})
            finally:
                self._updating = False

        threading.Thread(target=work, daemon=True).start()
        return {}

    # ================= 介面偏好 =================

    def ui_get(self, params: dict) -> dict:
        """讀介面偏好（ui.json）。"""
        return {"value": uistate.get(str(params.get("key") or ""))}

    def ui_set(self, params: dict) -> dict:
        uistate.set(str(params.get("key") or ""), params.get("value"))
        return {}

    # ================= 視窗（由外殼用 `attach_window()` 掛上）=================

    def attach_window(self, window) -> None:
        """把 pywebview 的視窗交給後端。

        ⚠ 一定要存進底線開頭的屬性：pywebview 會走訪 js_api 的公開成員，而 window 底下
          的 .NET Form 屬性鏈是無限的，會遞迴到 maximum recursion depth。
        """
        self._window = window

    def _win(self):
        if getattr(self, "_window", None) is None:
            raise RuntimeError("這個外殼沒有把視窗交給後端管")
        return self._window

    def win_minimize(self, _: dict) -> dict:
        self._win().minimize()
        return {}

    def _maximized(self) -> bool:
        """視窗是否最大化，問底層的 WinForms Form（`window.native.WindowState`）。

        ⚠ `window.state` 是 pywebview 給 JS 用的共享字典，與視窗狀態無關。
        ⚠ 不自己記旗標：雙擊標題列、Win+↑ 不會經過這裡。
        """
        form = getattr(self._win(), "native", None)
        if form is None:
            return False
        try:
            from System.Windows.Forms import FormWindowState
            return form.WindowState == FormWindowState.Maximized
        except Exception:
            return False

    def win_toggle_maximize(self, _: dict) -> dict:
        win = self._win()
        if self._maximized():
            win.restore()
        else:
            win.maximize()
        return {}

    def win_is_maximized(self, _: dict) -> dict:
        return {"value": self._maximized()}

    def set_hidden_hook(self, fn) -> None:
        """視窗縮到系統匣之後要做的事（跳氣泡通知）。"""
        self._on_hidden = fn

    def set_painted_hook(self, fn) -> None:
        """前端第一次畫好之後要做的事（顯示主視窗）。"""
        self._on_painted = fn

    def ui_painted(self, _: dict) -> dict:
        """前端回報第一份狀態已畫好。"""
        if self._on_painted is not None:
            self._on_painted()
        return {}

    def win_hide(self, _: dict) -> dict:
        """縮到系統匣。`tray_hint` 關閉時不跳通知。"""
        self._win().hide()
        if self._on_hidden is not None and uistate.get("tray_hint"):
            self._on_hidden()
        return {}

    def win_close(self, _: dict) -> dict:
        """使用者按了自繪的 ✕，決定詢問、縮小或結束。

        ⚠ 不用系統對話框：強制回應會凍結視窗，而結束程序期間介面要繼續更新。
        """
        choice = uistate.get("on_close")
        if choice == "tray":
            return self.win_hide({})
        if choice == "quit":
            return self.win_quit({})
        self._channel.send("confirm_close", None)
        return {}

    def update_restart(self, _: dict) -> dict:
        """使用者選「立即重新啟動」：排定啟動新版的背景工作，然後關閉自己。

        ⚠ 順序不可反：`restart()` 等的是這個 PID。選「稍後」時不排定任何事。
        """
        from core import updater
        if not updater.restart():
            raise RuntimeError("排不了重新啟動，請自己關掉再開一次")
        return self.win_quit({})

    def win_quit(self, _: dict) -> dict:
        """結束程式：先跑完結束程序，再關視窗。

        ⚠ 開執行緒做，不可擋住這次呼叫：畫面會停止更新。前端收到 `closing` 事件顯示進度。
        """
        self._channel.send("closing", None)

        def work():
            if self.is_running():
                self._runner.request_stop()
                self._runner.join(timeout=CLOSE_TIMEOUT)
            # ⚠ 拆視窗前先關閉通道：`destroy()` 不會觸發 `closing`，
            #   之後的 evaluate_js 會產生 ObjectDisposedException 寫進紀錄。
            self._channel.close()
            try:
                self._win().destroy()
            except Exception:
                pass        # 視窗已關閉

        threading.Thread(target=work, daemon=True).start()
        return {}

    def open_external(self, params: dict) -> dict:
        """用系統瀏覽器開連結。⚠ 只接受 http/https。"""
        url = str(params.get("url") or "")
        if url.startswith(("http://", "https://")):
            webbrowser.open(url)
        return {}

    # ================= 雜項 =================

    def ping(self, _: dict) -> dict:
        return {"pong": True}
