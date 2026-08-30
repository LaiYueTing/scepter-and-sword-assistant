"""前端叫得到的方法。一個方法一件事，全部在這裡登記。

⚠ **會等的事情不要讓前端乾等。** `test` 要做 adb connect（逾時 20 秒）、`discover`
  要探測一整排連接埠、更新要下載一百多 MB——這幾個都是「先回一句好，做完再推事件
  回去」，否則介面看起來就像當掉。判斷哪些要這樣做的準則很簡單：**做的事會不會
  超過一次畫面更新**。

⚠ **執行中不能改設定。** 引擎是在建立時才套用開關的（`_apply_options`），中途改
  不會生效。讓使用者以為改了有用，比不給改更糟。
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path
from typing import Any

from core import confedit, logger, optionmeta, uistate
from core.config import (ROOT, VERSION, WEEKDAY_NAMES, Config, TaskConfig,
                         resource_file)
from .bridge import Channel

log = logger.get("gui")

# 關視窗時等收尾的上限。收尾要逐層退出頁面，每步之間有等待動畫的時間，
# dungeon 那份是 2.5×3＋2 秒；留 30 秒有餘裕，卡住也不會讓視窗關不掉。
CLOSE_TIMEOUT = 30


def _open_in_shell(path: Path) -> None:
    """用系統預設程式開啟檔案或資料夾。

    ⚠ 不用 `webbrowser.open`：那支對資料夾在某些 Windows 設定下會拿去開瀏覽器。
    """
    try:
        os.startfile(str(path))                     # type: ignore[attr-defined]
    except AttributeError:                          # 非 Windows，開發時才會走到
        subprocess.run(["xdg-open", str(path)], check=False)


class Api:
    """方法表。每個公開方法就是一個前端叫得到的 method。"""

    def __init__(self, channel: Channel):
        self._channel = channel
        # ⚠ 底線開頭：pywebview 會走訪公開成員，而 Config 底下掛著 Path，
        #   屬性鏈長得沒有必要讓它去走。
        self._cfg: Config | None = None
        self._runner = None
        self._discovering = False
        self._updating = False
        self._release = None            # 查到的新版，等使用者決定要不要裝
        self._window = None             # 網頁版才會掛，見 attach_window
        # 縮到系統匣之後要說一聲：隱藏之後畫面上完全沒有痕跡，不講的話使用者
        # 會以為程式關掉了，再啟動一次——而那會被防多開擋下來。
        self._on_hidden = None

    # ================= 設定 =================

    def state(self, _: dict) -> dict:
        """介面啟動時要的全部資料，一次拿完。"""
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
            # 中文名直接取自腳本的 `name:`，不另外維護對照表——維護兩份就會有
            # 不一致的那天，這個專案在改名時已經現形過一次。
            "title": optionmeta.task_label(t.name),
            "enabled": t.enabled,
            "repeat": t.repeat,
            "repeat_hint": optionmeta.REPEAT_HINTS.get(t.name, ""),
            # 每週與每日是**兩個不同的鍵**，寫錯地方會讓腳本從「每週一」變成
            # 「每天」（或反過來整個不排程）。所以模式在後端就決定好，前端只編
            # 它該編的那一個。
            "mode": "weekly" if t.weekly else "daily",
            "daily_at": [f"{h:02d}:{m:02d}" for h, m in t.times],
            "weekly_at": [f"{WEEKDAY_NAMES[d]} {h:02d}:{m:02d}"
                          for d, h, m in t.weekly],
            "schedule": t.describe(),
            "catch_up": t.catch_up,
            "next_run": nxt.isoformat() if nxt else "",
        }

    @staticmethod
    def _template_options() -> dict[str, Any]:
        """設定範本裡的預設值。

        ⚠ **使用者的 `config.yaml` 不一定有全部的鍵。** 開關是一路加上去的，而舊的
          設定檔不會自己長出新的那幾行——只列 `cfg.options` 的話，介面上就會**少掉
          一整批選項**（實測使用者那份只有 15 個，程式其實認得 30 個，缺的全是競技場
          與討伐的調整項）。而且**沒有任何徵兆**：畫面看起來正常，只是短了一截。

        ⚠ 拿範本當預設是安全的：`config.example.yaml` 的值和腳本裡 `${鍵:預設}` 的
          預設是同一組（跑一次比對確認過），所以顯示出來的就是「不填的話會怎樣」。
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
        """開關與數值，附上標籤、說明、範圍與所屬腳本。

        ⚠ 對照表在 `core/optionmeta.py`，**前端不要自己抄一份**。漏掉的鍵會掉進
          「其他」分頁並顯示原始鍵名——`guild_donate_free` 就是這樣被使用者抓到的。
        """
        # 範本補底、使用者的設定覆蓋上去。順序照範本走，新舊設定檔看到的排列才一致。
        merged = {**Api._template_options(), **cfg.options}

        items: dict[str, dict] = {}
        for key, value in merged.items():
            label, hint = optionmeta.OPTION_LABELS.get(key, (key, ""))
            # ⚠ 不是全部都是開關。`buy_counts = 1`、`raid_join_players = 10`
            #   這些是數值，混在一起的話介面會把它們畫成核取方塊——勾一下就把
            #   10 變成 True，而設定檔那邊還看不出哪裡怪。
            entry: dict[str, Any] = {
                "value": value, "label": label, "hint": hint,
                # 「這是上一個開關的子項目」是**資料**，縮排怎麼畫交給介面決定。
                # 標籤字串裡不放排版字元——見 core/optionmeta.SUB_OPTIONS。
                "sub": key in optionmeta.SUB_OPTIONS,
            }
            if isinstance(value, bool):
                entry["kind"] = "bool"
            else:
                lo, hi, suffix, decimals = optionmeta.OPTION_RANGES.get(
                    key, (0, 99, "", 0))
                # ⚠ 小數位是必要的：raid_plateau_players 預設 6.5，用整數欄位會被
                #   無聲地寫回 6，使用者只是打開介面看一眼，門檻就被改掉了。
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
        """就地改寫 config.yaml。

        ⚠ 走 `core/confedit.py` 而不是 yaml.dump——設定檔的註解就是使用者的說明書，
          dump 一趟會把它們全部洗掉，介面省下的那點力氣完全不划算。
        """
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
        """用系統預設程式開啟設定檔或紀錄資料夾——介面沒做到的欄位仍然改得到。"""
        what = params.get("what")
        _open_in_shell(self._cfg.path if what == "config" else ROOT / "logs")
        return {}

    # ---- 內建的設定檔編輯器 ----
    #
    # ⚠ **有了介面上的開關，為什麼還要讓人編原文？** 因為 `config.yaml` 裡有一整批
    #   介面上沒有、也不該有的東西：`adb` 那一段、`runtime` 的補跑與讓路門檻、
    #   腳本清單本身。以前那些只能按「開啟設定檔」丟給記事本——而記事本沒有語法
    #   檢查，存一份壞掉的設定檔下去，要等下一次啟動才失敗，而那多半是半夜。

    def config_read(self, _: dict) -> dict:
        """把 config.yaml 的原文讀出來。"""
        path = self._cfg.path
        raw = path.read_bytes()
        return {"path": str(path), "text": raw.decode("utf-8")}

    def config_write(self, params: dict) -> dict:
        """把編輯器裡的原文寫回 config.yaml。

        ⚠ **先寫到旁邊、用真正的載入流程驗過，再換上去。** 只檢查 YAML 語法不夠：
          `daily_at: 8:00` 是合法的 YAML（會被讀成 480），時間格式錯、腳本名打錯
          都要等到執行那一刻才炸。拿 `Config.load()` 去驗等於走了一次真實路徑，
          而且**驗不過的時候 config.yaml 一個位元組都沒被動到**。

        ⚠ 換行沿用原檔，理由和 `confedit` 那邊完全相同：Windows 上直接寫換行字元
          會被再轉一次，原檔若本來就是 CRLF 就變成每行之間多一個空行。
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
            # ⚠ PyYAML 的訊息是英文的（"while parsing a flow sequence"），直接丟
            #   給使用者只會看到「有東西壞了」。前面補一句說清楚**檔案沒有被動到**
            #   ——那是他當下最需要知道的事。
            raise RuntimeError(
                "設定檔沒有寫入，因為這份內容載不起來：" + chr(10) + str(e)) from None
        else:
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)

        self._cfg = Config.load()
        log.info("設定檔已由內建編輯器整份寫回")
        return {}

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

        from .runner import RunnerThread          # 延後載入：會拉進 cv2
        self._runner = RunnerThread(
            cfg, tasks, self._channel, one_shot=bool(params.get("once")))
        self._runner.start()
        self._channel.send("running", True)
        return {}

    def stop(self, _: dict) -> dict:
        if not self.is_running():
            raise RuntimeError("沒有在執行")
        self._runner.request_stop()
        # ⚠ 收尾期間的等待不能被打斷，所以這裡不等它。按下停止到真正結束實測
        #   14～18 秒，介面要出聲，否則看起來像當掉。這一句只是開頭，接下來
        #   引擎會逐步把「收尾中　第 N 步」推上來蓋掉它。
        self._channel.send("status", "停止中，正在執行收尾動作 ⋯")
        return {}

    def join(self, params: dict) -> dict:
        """等收尾跑完。關視窗時用，逾時就放棄。"""
        if self.is_running():
            self._runner.join(timeout=float(params.get("timeout") or 30))
        return {"running": self.is_running()}

    # ================= 裝置 =================

    def test(self, _: dict) -> dict:
        """連一次看看。慢，所以開執行緒做，結果用事件推回去。"""
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
                # AdbError 的訊息本身就是給人看的檢查清單，原樣送過去
                self._channel.send("tested", {"ok": False, "text": str(e)})

        threading.Thread(target=work, daemon=True).start()
        return {}

    def discover(self, params: dict) -> dict:
        """探索可用的模擬器。`auto` 為真時是開視窗自動觸發的那一次。

        ⚠ 慢的是 `adb connect`：候選埠只要有一個「通得了 TCP 卻不是 adb」，那一發
          就會卡到逾時。所以絕不能在請求裡直接做完。

        ⚠ **自動觸發的那次不做多埠掃描**（`deep=False`）。對同一台遠端主機連敲十幾
          個埠會被防毒判定成連接埠掃描而封鎖整台機器，而開視窗是使用者隨手就會做
          很多次的動作。設定檔已經指名埠號時只敲那一個，本機則不受限制。
        """
        if self._discovering:
            raise RuntimeError("正在探索中")
        self._discovering = True

        def work():
            from core import discover
            from core.adb import Device
            try:
                # ⚠ 刻意不呼叫 dev.connect()：探索的用途就是「還不知道要連哪一台」，
                #   connect() 連不上會丟例外，整個探索就白做了。
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
            # 旗標排在最前面：收起來的下拉只看得到開頭那段，「這台不能用」
            # 不能落在被切掉的那一截裡。
            "label": f.label(want_size, want_dpi),
            # 多行版給 tooltip。單行會被 view 從中間省略，而埠號與解析度
            # 剛好都在省略號裡——那正是使用者要看的兩件事。
            "detail": f.detail(want_size, want_dpi),
            "usable": f.is_usable,
            # 規格不符比「連不上」更難查——每個模板都會比不中，而紀錄只會寫
            # 「沒有規則成立」。所以清單上直接標出來。
            "ok_size": f.matches_spec(want_size, want_dpi),
        }

    # ================= 更新 =================

    def update_check(self, params: dict) -> dict:
        """查有沒有新版。自動查的那條路查不到就安靜，沒網路不是使用者當下關心的事。

        ⚠ **回報要分得出「已經是最新」和「查不到」。** 兩者在 `check()` 都是 None，
          而介面會據此跳一句話——沒網路時說「已經是最新版本」就是在說謊。
        """
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
                # 空字串＝真的問到了 GitHub。有值就是「查不到」的原因，
                # 介面要說的是那一句，不是「已經是最新版本」。
                "error": err,
                # 自動查到的那條路只把按鈕點亮，不跳框
                "quiet": bool(params.get("quiet")),
            })

        threading.Thread(target=work, daemon=True).start()
        return {}

    def update_apply(self, _: dict) -> dict:
        """下載並換檔，成功就排一次重新啟動。

        ⚠ **執行中不更新。** 換檔要重新啟動才生效，而重新啟動會中斷正在打的副本
          或討伐，那一次次數不會回來。
        """
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
                    # ⚠ 只推事件，不寫紀錄——一秒好幾筆，寫進去會把紀錄洗掉。
                    self._channel.send("update_progress",
                                      {"done": done, "total": total})

                path = updater.download(rel, on_progress)
                if path is None:
                    raise RuntimeError("下載失敗，請稍後再試或到發布頁手動下載")
                ok, why = updater.apply(path)
                if not ok:
                    raise RuntimeError(why)
                # ⚠ **不要在這裡就 restart()。** 它排的是一個「等這個行程結束
                #   就啟動新版」的背景 PowerShell，而使用者不一定當場重啟——
                #   那個 PowerShell 會一直潛伏著，等他哪天關掉程式，新版就自己
                #   跳出來，還可能和他自己雙擊的那次撞成「助手已經在執行中」。
                #   改由 update_restart() 觸發，那才是明確的意思表示。
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
        """讀介面自己的偏好（主題、視窗大小、關閉時的選擇）。

        ⚠ **和 config.yaml 分開，但兩份介面共用同一份。** 各存各的話，換一張臉
          主題就跳回預設，而使用者不會知道為什麼。
        """
        return {"value": uistate.get(str(params.get("key") or ""))}

    def ui_set(self, params: dict) -> dict:
        uistate.set(str(params.get("key") or ""), params.get("value"))
        return {}

    # ================= 視窗 =================
    #
    # ⚠ 這幾個只有網頁版（pywebview）會用到——那邊的視窗握在 Python 手上。
    #   視窗由外殼在建立 Api 之後用 `attach_window()` 掛上來，沒掛就代表這條路
    #   不存在，要直接說清楚而不是安靜地沒反應。

    def attach_window(self, window) -> None:
        """把 pywebview 的視窗交給後端管。

        ⚠ **一定要存進底線開頭的屬性。** pywebview 會走訪 js_api 物件的**每一個
          公開成員**來決定要暴露什麼給 JS，而 pywebview 的 window 底下掛著 .NET 的
          Form——它的屬性鏈是無限的：

              window.native.AccessibilityObject.Bounds.Empty.Empty.Empty.Empty…

          掃到那裡就會一路遞迴到 `maximum recursion depth exceeded`，**每秒刷幾十行
          錯誤，而視窗還是開得起來**，所以很容易誤判成「只是有雜訊」。
          底線開頭的名字會被跳過，這是唯一的解法。

        ⚠ 同一個理由，`_channel` 也是私有的。
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
        """視窗是不是最大化。

        ⚠ **不要問 `window.state`。** 那個名字很像視窗狀態，實際上是 pywebview 給 JS
          用的**共享資料字典**（`class State(dict)`），和最大化毫無關係。原本寫成
          `str(window.state) == "maximized"`，那個判斷**永遠是 False**——症狀是
          「最大化之後按不回原本的大小」，而且看程式碼完全看不出問題。

        ⚠ 要問的是底層的 WinForms Form（`window.native.WindowState`）。**不要自己記
          一個旗標**：使用者可以雙擊標題列、拖到螢幕頂端、用 Win+↑ 最大化，那些都
          不會經過我們，旗標一定會和現實脫節。
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
        """視窗縮起來之後要做的事（網頁版拿去跳系統匣的氣泡通知）。

        ⚠ **隱藏之後畫面上完全沒有痕跡**，不講一聲的話使用者會以為程式關掉了，
          然後再啟動一次——而那會被防多開擋下來，看起來就像「按了沒反應」。
        """
        self._on_hidden = fn

    def win_hide(self, _: dict) -> dict:
        self._win().hide()
        if self._on_hidden is not None:
            self._on_hidden()
        return {}

    def win_close(self, _: dict) -> dict:
        """使用者按了自繪的 ✕。決定要問、要縮、還是要結束。

        ⚠ **不用系統原生的對話框問。** 那是強制回應的，會把整個視窗凍住——而按下
          結束之後還要跑十幾秒的收尾，那段期間狀態列與紀錄面板都要繼續更新。
          所以把問題丟回前端，由它自繪的對話框處理。
        """
        choice = uistate.get("on_close")
        if choice == "tray":
            return self.win_hide({})
        if choice == "quit":
            return self.win_quit({})
        self._channel.send("confirm_close", None)
        return {}

    def update_restart(self, _: dict) -> dict:
        """換好檔之後、使用者選「立即重新啟動」時才走這條。

        排定「等這個行程結束就啟動新版」的背景工作，然後關掉自己。兩件事的
        順序不能反：`restart()` 等的就是這個 PID。

        ⚠ 選「稍後」的話這條不會跑，什麼都不排——下次使用者自己開就是新版。
        """
        from core import updater
        if not updater.restart():
            raise RuntimeError("排不了重新啟動，請自己關掉再開一次")
        return self.win_quit({})

    def win_quit(self, _: dict) -> dict:
        """真的要結束：先跑完收尾，再關視窗。

        ⚠ **收尾不能在這條呼叫裡等完。** 前端還在等這個 Promise，而收尾要逐層退回
          家園、每步之間有等動畫的時間（dungeon 那份是 2.5×3＋2 秒）。擋在這裡的話
          畫面整段不會更新，看起來就是當掉。
          所以開執行緒做，前端立刻收到 `closing` 事件去顯示「正在執行收尾動作」。
        """
        self._channel.send("closing", None)

        def work():
            if self.is_running():
                self._runner.request_stop()
                self._runner.join(timeout=CLOSE_TIMEOUT)
            # ⚠ **拆視窗之前一定要先收掉通道。** `destroy()` 不會觸發 `closing`
            #   事件（那是給「使用者關視窗」用的），所以外殼那邊的 `channel.close()`
            #   在這條路上不會跑到。少了這一行，收尾期間還會有紀錄往 `evaluate_js`
            #   送，而 WebView2 已經被處置——pywebview **自己 log 完才吞掉**那個
            #   `ObjectDisposedException`，我們的 try/except 接不到，於是二十幾行
            #   .NET traceback 一路寫進 assistant.log 和使用者的終端機。
            self._channel.close()
            try:
                self._win().destroy()
            except Exception:
                pass        # 視窗已經沒了就算了，反正接下來就是收工

        threading.Thread(target=work, daemon=True).start()
        return {}

    def open_external(self, params: dict) -> dict:
        """用系統瀏覽器開連結。⚠ 只放行 http/https——這個參數是前端給的。"""
        url = str(params.get("url") or "")
        if url.startswith(("http://", "https://")):
            webbrowser.open(url)
        return {}

    # ================= 雜項 =================

    def ping(self, _: dict) -> dict:
        return {"pong": True}
