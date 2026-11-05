"""杖劍傳說助手 —— 命令列進入點。

用法：
    python main.py doctor              檢查環境與連線
    python main.py shot                抓一張截圖存到 logs/
    python main.py watch               持續截圖，方便觀察畫面變化
    python main.py find <模板名>        測試模板比對分數
    python main.py tap <x> <y>         手動點擊，用來驗證座標
    python main.py run                 執行預設腳本
    python main.py run -t dungeon -n 5 執行 dungeon 腳本 5 次
"""

from __future__ import annotations

# ⚠ 排在所有重量級 import 之前，core.splash 只用標準庫。
from core import splash                                    # noqa: E402
splash.step("載入程式庫")

import argparse                                            # noqa: E402
import shutil                                              # noqa: E402
import sys                                                 # noqa: E402
import time                                                # noqa: E402
from datetime import datetime                              # noqa: E402
from pathlib import Path                                   # noqa: E402

import yaml                                                # noqa: E402

from core import logger, recorder, singleton, vision
from core.adb import AdbError, Device
from core.config import (
    LOG_DIR, SAMPLE_DIR, TEMPLATE_OUT_DIR, VERSION, Config, ConfigError,
    resource_files,
)
from core.engine import Engine, Script, ScriptError
from core.runner import Runner

log = logger.get("main")


def _load_config(args) -> Config:
    cfg = Config.load(args.config)

    # 剛從範本建立設定檔，裝置資訊還沒填，先停下來。
    if cfg.is_new:
        print(f"\n[資訊] 已建立設定檔：{cfg.path}")
        print("[提示] 請先開啟這個檔案設定要連的模擬器：")
        print("         同一台電腦　：device.serial 填 auto（範本已經是這樣）")
        print("         模擬器在別台：device.serial 留空，填 device.host 與 port")
        print("         （連接埠看模擬器的設定，MuMu 在「問題診斷 → ADB 調試埠」）")
        print("\n設定好之後再執行一次即可。")
        raise SystemExit(0)

    if args.host:
        cfg.device.host = args.host
        cfg.device.serial = None      # 有給 host 就不用序號
    if args.port:
        cfg.device.port = args.port
    if args.serial:
        cfg.device.serial = args.serial
    return cfg


def _device(args) -> Device:
    dev = Device(_load_config(args))
    dev.connect()
    return dev


def cmd_devices(args) -> int:
    """列出看得到的裝置，多開時用來查序號。

    預設會探索本機與設定檔 host 上常見的模擬器埠；`--no-scan` 只列已連上的。
    """
    from core import discover

    cfg = _load_config(args)
    dev = Device(cfg)

    if args.no_scan:
        found = [discover.Found(serial=s, state=st) for s, st in dev.list_devices()]
        for f in found:
            if f.is_usable:
                f.model, f.size, f.dpi = discover.describe(str(dev.adb), f.serial)
    else:
        print("正在探索 ...")
        found = discover.scan(dev)

    if not found:
        print("沒有偵測到任何裝置。請先啟動模擬器，並確認它允許遠端 ADB 連線"
              "設為『本機與遠端連線』。")
        return 1

    want = f"{cfg.device.width}x{cfg.device.height}"
    # ⚠ 用 logger.pad 按顯示寬度對齊，f-string 的 `:<24` 按字元數算。
    print("\n" + logger.pad("序號", 25) + logger.pad("狀態", 11)
          + logger.pad("解析度", 15) + "型號")
    for f in found:
        spec = f"{f.size}/{f.dpi}" if f.size else "-"
        flag = "" if f.matches_spec(want, cfg.device.dpi) else "  ← 解析度不符"
        print(logger.pad(f.serial, 25)
              + logger.pad(discover.state_text(f.state), 11)
              + logger.pad(spec, 15) + (f.model or "-") + flag)

    print(f"\n把序號填進 config.yaml 的 device.serial 即可指定要控制哪一台"
          "（跨機器的則拆成 host 與 port），或填 auto 自動選第一台。")
    if any(f.is_usable and not f.matches_spec(want, cfg.device.dpi) for f in found):
        print(f"⚠ 標示「解析度不符」的那幾台不能直接用：模板全依 {want}／"
              f"{cfg.device.dpi}dpi 裁，尺寸不對會每一條規則都比不中。")
    return 0


def cmd_update(args) -> int:
    """檢查並安裝新版，供排程與命令列使用者手動執行。

    ⚠ 不要排進自動流程：更新會換掉執行檔並要求重新啟動。
    """
    from core import updater

    print(f"目前版本：v{VERSION}")
    release = updater.latest()
    if release is None:
        print("查不到更新資訊（沒有網路，或還沒有發布任何版本）")
        return 1

    print(f"最新版本：v{release.version}（{release.size_text}）")
    if not updater.is_newer(release.version):
        print("已經是最新版本。")
        return 0
    if args.check:
        print(f"下載頁：{updater.PAGE}")
        return 0

    ok, why = updater.can_apply()
    if not ok:
        print(f"[錯誤] {why}")
        return 1

    last = -1

    def show(got: int, total: int) -> None:
        nonlocal last
        pct = got * 100 // total if total else 0
        if pct != last:                  # 每 1% 印一次
            last = pct
            # 回到行首覆蓋前一次的百分比
            print(chr(13) + f"下載中 {pct:3d}%", end="", flush=True)

    path = updater.download(release, show)
    print()
    if path is None:
        print("[錯誤] 下載失敗。請確認網路正常，或防毒有沒有擋下執行檔。")
        return 1

    ok, why = updater.apply(path)
    if not ok:
        print(f"[錯誤] {why}")
        return 1

    print(f"已更新到 v{release.version}。")
    if args.restart and updater.restart():
        print("正在重新啟動 …")
    else:
        print("下次啟動時生效。")
    return 0


def cmd_doctor(args) -> int:
    cfg = _load_config(args)
    print(f"設定檔目標裝置：{cfg.device.target}")

    try:
        dev = Device(cfg)
        print(f"adb 執行檔：{dev.adb}")
    except AdbError as e:
        print(f"[失敗] {e}")
        return 1

    try:
        dev.connect()
    except AdbError as e:
        print(f"[失敗] {e}")
        return 1

    print(f"型號：{dev.shell('getprop ro.product.model')}")
    print(f"Android：{dev.shell('getprop ro.build.version.release')}")

    t0 = time.time()
    img = dev.screencap()
    print(f"截圖：{img.shape[1]}x{img.shape[0]}，耗時 {time.time() - t0:.2f} 秒")

    n_tmpl = len(resource_files("templates", "*.png"))
    n_script = len(resource_files("scripts", "*.yaml"))
    print(f"模板：{n_tmpl} 張　腳本：{n_script} 份")

    # 檢查腳本引用的模板是否齊全（缺模板的規則會被停用）。
    print()
    have = {p.stem for p in resource_files("templates", "*.png")}

    # 「沒有任何腳本用到」要對照所有腳本的聯集。
    used_by_any: set[str] = set()
    for path in resource_files("scripts", "*.yaml"):
        try:
            used_by_any |= Script.load(
                path.stem, cfg.options).referenced_templates()
        except ScriptError as e:
            print(f"[警告] 腳本 {path.name} 讀取失敗：{e}")

    tasks = cfg.enabled_tasks or cfg.tasks
    if not tasks:
        print("[警告] 設定檔沒有啟用任何腳本")
    any_missing = False
    for task in tasks:
        try:
            script = Script.load(task.name, cfg.options)
        except ScriptError as e:
            print(f"[失敗] {e}")
            return 1
        referenced = script.referenced_templates()
        missing = sorted(referenced - have)
        print(f"腳本「{script.name}」（{task.name}）：{len(script.rules)} 條規則，"
              f"引用 {len(referenced)} 個模板　排程：{task.describe()}")
        if missing:
            any_missing = True
            print(f"  [警告] 缺少 {len(missing)} 個模板，相關規則會被停用：")
            for name in missing:
                print(f"          {name}")

    unused = sorted(have - used_by_any)
    if unused:
        print(f"[提示] 有 {len(unused)} 個模板沒有任何腳本用到："
              f"{'、'.join(unused)}")
    if not any_missing:
        print("模板齊全。")

    print("\n環境正常，可以開始使用。")
    return 0


def cmd_shot(args) -> int:
    dev = _device(args)
    name = args.name or datetime.now().strftime("%Y%m%d_%H%M%S")
    path = LOG_DIR / "shots" / f"{name}.png"
    dev.save_screencap(path)
    print(f"已存檔：{path}")
    return 0


def cmd_watch(args) -> int:
    dev = _device(args)
    out = LOG_DIR / "shots"
    print(f"每 {args.interval} 秒截圖一次，存到 {out}，按 Ctrl + C 停止")
    try:
        while True:
            name = datetime.now().strftime("%H%M%S")
            dev.save_screencap(out / f"{name}.png")
            print(f"  {name}.png")
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\n已停止")
    return 0


def cmd_record(args) -> int:
    """錄一段流程，只留下畫面有變化的關鍵幀，並拼成一張總覽圖。"""
    dev = _device(args)
    name = args.name or datetime.now().strftime("%H%M%S")

    folder = recorder.record_dir(name)
    frames = recorder.record(
        dev,
        duration=args.duration,
        interval=args.interval,
        threshold=args.threshold,
        max_frames=args.max_frames,
        save_dir=folder,          # 邊錄邊寫檔
    )
    if not frames:
        print("這段期間畫面完全沒有變化，沒有可用的關鍵幀")
        return 1

    total = len(frames)
    # 總覽圖從檔案重新讀（只讀抽樣需要的幾張）
    frames = recorder.load_frames(folder, max_frames=args.max_frames)
    sheet_path = LOG_DIR / "records" / f"{name}_總覽.png"
    vision.imwrite_unicode(sheet_path, recorder.contact_sheet(frames, cols=args.cols))

    print(f"\n關鍵幀 {total} 張：{folder}")
    print(f"總覽圖：{sheet_path}")
    return 0


def cmd_sheet(args) -> int:
    """從已存檔的錄製資料夾重做總覽圖。"""
    folder = recorder.record_dir(args.name)
    if not folder.is_dir():
        print(f"[失敗] 找不到錄製資料夾：{folder}")
        return 1

    frames = recorder.load_frames(
        folder, max_frames=args.max_frames, start=args.start, count=args.count
    )
    if not frames:
        print(f"[失敗] 資料夾裡沒有關鍵幀：{folder}")
        return 1

    suffix = f"_{args.start}" if args.start or args.count else ""
    sheet_path = LOG_DIR / "records" / f"{args.name}_總覽{suffix}.png"
    vision.imwrite_unicode(sheet_path, recorder.contact_sheet(frames, cols=args.cols))
    print(f"總覽圖（{len(frames)} 格）：{sheet_path}")
    return 0


def cmd_scan(args) -> int:
    """掃描整段錄製，找出出現指定模板的幀。"""
    folder = recorder.record_dir(args.name)
    if not folder.is_dir():
        print(f"[失敗] 找不到錄製資料夾：{folder}")
        return 1

    files = sorted(folder.glob("*.png"), key=lambda p: int(p.stem.split("_")[0]))
    if not files:
        print(f"[失敗] 資料夾裡沒有關鍵幀：{folder}")
        return 1

    hits = 0
    print(f"掃描 {len(files)} 張，尋找 {args.template}（門檻 {args.threshold}）\n")
    for p in files:
        img = vision.imread_unicode(p)
        try:
            m = vision.find(img, args.template, args.threshold, hint=False)
        except FileNotFoundError as e:
            print(f"[失敗] {e}")
            return 1
        if args.absent:
            # 反向：列出沒有這個模板的幀
            if m is None:
                hits += 1
                print(f"  {p.stem}")
        elif m:
            hits += 1
            print(f"  {p.stem:<20} {m.score:.3f}  中心 ({m.center[0]}, {m.center[1]})")
        elif args.verbose:
            print(f"  {p.stem:<20} {vision.score(img, args.template):.3f}")

    print(f"\n共 {hits} 張{'未命中' if args.absent else '命中'}")
    return 0


def cmd_explain(args) -> int:
    """對當前畫面逐條評估腳本規則，說明會觸發哪一條。"""
    from core import vision as _v

    cfg = _load_config(args)
    # 沒指定 -t 就用第一個啟用的腳本
    name = args.task or (cfg.enabled_tasks or cfg.tasks)[0].name

    script = Script.load(name, cfg.options)
    # 套用 config 開關，與實際執行一致
    from core.engine import apply_options
    for rule in apply_options(script.rules, cfg.options):
        print(f"（已依設定停用：{rule.name} — {rule.when_option}）")

    if args.source:
        src = _find_shot(args.source)
        if src is None:
            print(f"[失敗] 找不到截圖：{args.source}")
            return 1
        screen = _v.imread_unicode(src)
        print(f"畫面來源：{src.name}\n")
    else:
        screen = _device(args).screencap()
        print()

    default_th = cfg.runtime.threshold
    fired = None

    for rule in script.rules:
        if rule._disabled:
            continue
        th = rule.threshold if rule.threshold is not None else default_th
        notes = []
        ok = True

        for name in rule.require:
            try:
                s = _v.score(screen, name)
            except FileNotFoundError:
                notes.append(f"require {name}=缺模板")
                ok = False
                continue
            notes.append(f"require {name}={s:.2f}")
            if s < th:
                ok = False

        if rule.measure:
            # 不模擬 smooth：只有一張畫面。
            from core.engine import (_measure_text, describe_measure,
                                     measure_ok, measure_raw)
            value = measure_raw(screen, rule.measure)
            notes.append(f"{rule.measure.get('log', 'measure')}="
                         f"{_measure_text(value, rule.measure)}"
                         f"（要 {describe_measure(rule.measure)}）")
            if not measure_ok(value, rule.measure):
                ok = False

        if rule.blob:
            found = _v.find_blob(screen, rule.blob)
            want_absent = bool(rule.blob.get("absent"))
            notes.append("blob=" + (f"{int(found.score)}px@{found.center}"
                                    if found else "無")
                         + ("（要不在）" if want_absent else ""))
            if bool(found) == want_absent:
                ok = False

        if rule.template:
            best = 0.0
            for name in rule.template:
                try:
                    best = max(best, _v.score(screen, name, rule.region))
                except FileNotFoundError:
                    notes.append(f"{name}=缺模板")
                    ok = False
            if rule.template and not any("缺模板" in n for n in notes):
                notes.append(f"template={best:.2f}")
            if best < th:
                ok = False
        elif rule.absent:
            worst = 0.0
            for name in rule.absent:
                try:
                    worst = max(worst, _v.score(screen, name, rule.region))
                except FileNotFoundError:
                    notes.append(f"{name}=缺模板")
                    ok = False
            notes.append(f"absent={worst:.2f}")
            if worst >= th:
                ok = False

        mark = "→ 觸發" if ok and fired is None else ("  可成立" if ok else "  -")
        if ok and fired is None:
            fired = rule
        # 按顯示寬度對齊
        print(f"{logger.pad(mark, 8)} {logger.pad(rule.name, 34)} {'  '.join(notes)}")

    print()
    if fired:
        print(f"結論：會執行「{fired.name}」")
        for action in fired.actions:
            for verb, arg in action.items():
                # 沒有參數的動作（count、finish）讀出來是 None，不印參數
                print(f"   {verb}" + (f": {arg}" if arg is not None else ""))
    else:
        print("結論：沒有規則成立，引擎會停在等待狀態")
    return 0


# selftest 用的固定設定，不跟著使用者當下的 config，比對基準才穩定。
SELFTEST_OPTIONS = {
    # 自動副本
    "claim_reward": True,
    "stop_when_no_count": True,
    "auto_battle_mode": True,
    "like_teammates": True,
    "buy_counts": 1,
    "accept_with_partners": True,
    # 自動公會討伐
    "claim_raid_reward": True,
    "wait_for_others": True,
}


def _selftest_one(task: str, expected_file: Path, cfg: Config) -> tuple[int, list]:
    """驗證單一腳本，回傳（通過數, 失敗清單）。"""
    from core.engine import apply_options

    sample_dir = SAMPLE_DIR
    cases = yaml.safe_load(expected_file.read_text(encoding="utf-8")) or []
    script = Script.load(task, cfg.options)

    print(f"腳本「{script.name}」（{expected_file.name}）")

    engine = Engine.__new__(Engine)          # 只借用判斷邏輯，不連裝置
    engine.script = script
    engine.cfg = cfg

    passed, failed = 0, []
    for case in cases:
        path = sample_dir / case["file"]
        want = case.get("rule") or ""
        if not path.is_file():
            failed.append((case["file"], want or "（無）", "樣本檔不存在"))
            print(f"  [失敗] {case['file']:<28} {case['desc']}")
            continue

        screen = vision.imread_unicode(path)
        # 每個樣本都從乾淨狀態判斷。案例欄位：
        #   options:  覆寫標準設定，驗證不同開關組合
        #   fired:    走到這張畫面之前已用完的規則（每輪只做一次的附帶動作）
        #   flags:    走到這張畫面時已設定的旗標；沒寫就視為一律成立
        #
        # ⚠ `_today` 要歸零：Script.load 從正式的 state.json 讀入，不可讓結果隨當天次數改變。
        engine._flags = set(case["flags"]) if "flags" in case else None
        used = set(case.get("fired") or [])
        for rule in script.rules:
            rule._since = 0.0
            rule._disabled = False
            rule._today = 0
            rule._fires = max(rule.max_fires, 1) if rule.name in used else 0
        apply_options(script.rules, {**SELFTEST_OPTIONS, **(case.get("options") or {})})
        hit = engine._match_rule(screen)
        actual = hit[0].name if hit else ""

        # 有 sustain 的規則第一輪不會成立。預期的正是這種規則時，把計時調滿再判一次。
        if actual != want and want:
            for rule in script.rules:
                if rule.name == want and rule.sustain:
                    rule._since = time.time() - rule.sustain - 1
                    hit = engine._match_rule(screen)
                    actual = hit[0].name if hit else ""
                    break

        if actual == want:
            passed += 1
            print(f"  [通過] {case['file']:<28} {case['desc']}")
        else:
            failed.append((case["file"], want, actual or "（沒有規則成立）"))
            print(f"  [失敗] {case['file']:<28} {case['desc']}")

    print(f"  —— 通過 {passed} / {len(cases)}\n")
    return passed, failed


def cmd_selftest(args) -> int:
    """拿 samples/ 的實機畫面驗證規則判斷。

    不指定 -t 時驗證每一份有預期結果檔的腳本（模板是共用的）。
    """
    sample_dir = SAMPLE_DIR
    cfg = _load_config(args)

    if args.task:
        targets = [(args.task, sample_dir / f"expected_{args.task}.yaml")]
    else:
        targets = [(p.stem.removeprefix("expected_"), p)
                   for p in sorted(sample_dir.glob("expected_*.yaml"))]

    if not targets:
        print(f"[失敗] {sample_dir} 裡沒有任何 expected_<腳本>.yaml")
        return 1

    total_pass, total_case, all_failed = 0, 0, []
    print(f"（以標準設定驗證：{'、'.join(k for k, v in SELFTEST_OPTIONS.items() if v)}）\n")

    for task, expected_file in targets:
        if not expected_file.is_file():
            print(f"[失敗] 找不到預期結果檔：{expected_file}")
            return 1
        try:
            passed, failed = _selftest_one(task, expected_file, cfg)
        except ScriptError as e:
            print(f"[失敗] {e}")
            return 1
        cases = yaml.safe_load(expected_file.read_text(encoding="utf-8")) or []
        total_pass += passed
        total_case += len(cases)
        all_failed += [(task, *f) for f in failed]

    print(f"合計通過 {total_pass} / {total_case}")
    if all_failed:
        print("\n不符預期的項目：")
        for task, name, want, actual in all_failed:
            print(f"  [{task}] {name}\n     預期：{want}\n     實際：{actual}")
        return 1
    print("全部符合預期。")
    return 0


def cmd_clean(args) -> int:
    """清掉執行過程產生的截圖與錄製，samples/ 不受影響。"""
    targets = [
        (LOG_DIR / "records", "流程錄製"),
        (LOG_DIR / "frames", "除錯截圖"),
        (LOG_DIR / "shots", "手動截圖"),
    ]
    if args.all:
        targets.append((LOG_DIR, "執行紀錄"))

    total = 0
    for path, desc in targets:
        if not path.exists():
            continue
        files = [p for p in path.rglob("*") if p.is_file()]
        size = sum(p.stat().st_size for p in files)
        if not files:
            continue

        print(f"{desc:<10} {len(files):>5} 個檔　{size / 1024 / 1024:>8.1f} MB")
        total += size
        if not args.dry_run:
            if path == LOG_DIR:
                for p in files:
                    if p.suffix == ".log" or p.name.startswith("assistant"):
                        p.unlink()
            else:
                shutil.rmtree(path)

    if total == 0:
        print("沒有需要清理的檔案。")
        return 0

    action = "可釋放" if args.dry_run else "已釋放"
    print(f"\n{action} {total / 1024 / 1024:.1f} MB")
    if args.dry_run:
        print("（這是試算，加上 --yes 才會真的刪除）")
    else:
        print("samples/ 的回歸測試樣本已保留。")
    return 0


def cmd_find(args) -> int:
    if args.source:
        src = _find_shot(args.source)
        if src is None:
            print(f"[失敗] 找不到截圖：{args.source}")
            return 1
        screen = vision.imread_unicode(src)
        print(f"比對對象：{src.name}")
    else:
        screen = _device(args).screencap()

    try:
        s = vision.score(screen, args.template)
    except FileNotFoundError as e:
        print(f"[失敗] {e}")
        return 1

    matches = vision.find_all(screen, args.template, args.threshold, hint=False)
    print(f"最佳分數：{s:.3f}（門檻 {args.threshold}）")
    for m in matches:
        print(f"  {m.score:.3f}  中心 ({m.center[0]}, {m.center[1]})  左上 ({m.x}, {m.y})")
    if not matches:
        print("  沒有超過門檻的結果")

    if args.save:
        path = LOG_DIR / "shots" / f"find_{args.template}.png"
        vision.imwrite_unicode(path, vision.annotate(screen, matches))
        print(f"標註圖：{path}")
    return 0


def _find_shot(source: str) -> Path | None:
    """依名稱找截圖：先看 shots/，再遞迴找 records/，最後當成路徑。"""
    direct = Path(source)
    if direct.is_file():
        return direct

    named = LOG_DIR / "shots" / f"{source}.png"
    if named.is_file():
        return named

    hits = sorted((LOG_DIR / "records").rglob(f"{source}*.png"))
    return hits[0] if hits else None


def cmd_text(args) -> int:
    """用系統內建的 OCR 讀一塊區域，用來調 log_text 的參數。"""
    from core import ocr

    if args.source:
        src = _find_shot(args.source)
        if src is None:
            print(f"[失敗] 找不到截圖：{args.source}")
            return 1
        screen = vision.imread_unicode(src)
        print(f"畫面來源：{src.name}")
    else:
        screen = _device(args).screencap()

    if args.region and len(args.region) != 4:
        print("[失敗] 區域要給四個數字：x y w h")
        return 1
    region = tuple(args.region) if args.region else None

    text = ocr.read(screen, region, scale=args.scale, binary=args.binary,
                    trim_right=args.trim_right)
    where = f"{region}" if region else "整張畫面"
    extra = f"，亮度門檻 {args.binary}" if args.binary is not None else ""
    if args.trim_right:
        extra += f"，右端扣 {args.trim_right}px"
    print(f"區域 {where}　放大 x{args.scale}{extra}")
    print(f"讀到：{text or '（讀不到）'}")
    return 0


def cmd_crop(args) -> int:
    """從截圖裁一塊區域存成模板。"""
    src = _find_shot(args.source)
    if src is None:
        print(f"[失敗] 找不到截圖：{args.source}")
        return 1

    img = vision.imread_unicode(src)
    h, w = img.shape[:2]
    x, y = max(0, args.x), max(0, args.y)
    cw, ch = min(args.w, w - x), min(args.h, h - y)
    if cw <= 0 or ch <= 0:
        print(f"[失敗] 裁切範圍超出畫面（畫面為 {w}x{h}）")
        return 1

    out = TEMPLATE_OUT_DIR / f"{args.name}.png"
    vision.imwrite_unicode(out, img[y:y + ch, x:x + cw])
    print(f"已建立模板：{out}（{cw}x{ch}，來自 {x},{y}）")
    return 0


def cmd_tap(args) -> int:
    dev = _device(args)
    dev.tap(args.x, args.y, jitter=0)
    print(f"已點擊 ({args.x}, {args.y})")
    return 0


def _claim_single_instance(gui: bool) -> bool:
    """確認沒有另一個助手在跑。已經有的話把那個視窗叫回前景，回傳 False。

    `gui` 決定訊息去對話框還是終端機，以及是否開門讓別人叫。
    ⚠ 只給會操作裝置的命令用（介面與 run）。
    """
    if singleton.acquire(windowed=gui) is not None:
        return True

    woke = singleton.wake_existing()
    if gui and woke:
        return False        # 既有的視窗會自己說明

    # ⚠ 命令列敲到了也要印一行：視窗跳出來的是另一個畫面。
    text = ("助手已經在執行中"
            + ("，已切換到原本那個視窗。" if woke
               else "（可能是工作排程器在背景跑的那一份）。"))
    if gui:
        splash.close()      # 啟動畫面是 always on top，會蓋住提示框
        logger.message_box("杖劍傳說助手", text, logger.MB_INFO)
    else:
        print(f"[失敗] {text}")
    return False


def cmd_gui(args) -> int:
    """開圖形介面，不帶參數執行時走這裡。

    ⚠ 前端資源要先建置（`cd gui/ui && npm run build`），沒建置時跳對話框說明。
    ⚠ 啟動畫面由 `gui/app.py` 在視窗載好時關閉，這裡只處理開不了視窗的路徑。
    """
    if not _claim_single_instance(gui=True):
        splash.close()
        return 0
    splash.step("載入介面")
    try:
        from gui.app import main as gui_main
    except ImportError as e:
        splash.close()
        logger.message_box(
            "無法開啟圖形介面",
            f"缺少 pywebview：{e}\n\n安裝：python -m pip install -r requirements.txt")
        return 1
    return gui_main()

def cmd_run(args) -> int:
    """依排程輪流執行啟用的腳本，排程在 core/runner.py。"""
    if not _claim_single_instance(gui=False):
        return 1
    cfg = _load_config(args)

    # 指定 -t 就只跑那一個，跑完結束
    if args.task:
        tasks = [cfg.task_of(args.task)]
        one_shot = True
    else:
        tasks = cfg.enabled_tasks
        one_shot = args.once
        if not tasks:
            print("[失敗] 設定檔裡沒有啟用任何腳本"
                  "（tasks 底下的 enabled 全是 false）")
            return 1

    if args.repeat is not None:
        for task in tasks:
            task.repeat = args.repeat

    try:
        return Runner(cfg, tasks, one_shot=one_shot, dry_run=args.dry_run,
                      interactive=True).run()
    except ScriptError as e:
        print(f"[失敗] {e}")
        return 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="杖劍傳說助手",
        description="透過 ADB 後台操作 Android 模擬器的自動化助手",
    )
    p.add_argument("-c", "--config", help="設定檔路徑")
    p.add_argument("--host", help="覆寫模擬器 IP")
    p.add_argument("--port", type=int, help="覆寫 ADB 連接埠")
    p.add_argument(
        "--serial", help="直接指定 adb 序號（例如 emulator-5556），或 auto",
    )

    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", help="檢查環境與連線").set_defaults(func=cmd_doctor)

    sp = sub.add_parser("update", help="檢查並安裝新版")
    sp.add_argument("--check", action="store_true", help="只查有沒有新版，不下載")
    sp.add_argument("--restart", action="store_true", help="裝完直接重新啟動")
    sp.set_defaults(func=cmd_update)
    sp = sub.add_parser("devices", help="探索可用裝置（多開時查序號與連接埠）")
    sp.add_argument("--no-scan", action="store_true",
                    help="只列出已連上的，不主動掃描常見的模擬器連接埠")
    sp.set_defaults(func=cmd_devices)

    sp = sub.add_parser("shot", help="抓一張截圖")
    sp.add_argument("name", nargs="?", help="檔名（不含副檔名）")
    sp.set_defaults(func=cmd_shot)

    sp = sub.add_parser("watch", help="持續截圖")
    sp.add_argument("-i", "--interval", type=float, default=1.0, help="間隔秒數")
    sp.set_defaults(func=cmd_watch)

    sp = sub.add_parser("record", help="錄製流程，抽出有變化的關鍵幀")
    sp.add_argument("name", nargs="?", help="這段錄製的名稱")
    sp.add_argument("-d", "--duration", type=float, default=60, help="錄製秒數")
    sp.add_argument("-i", "--interval", type=float, default=0.4, help="抓幀間隔")
    sp.add_argument(
        "-t", "--threshold", type=float, default=6.0,
        help="判定畫面換了的差異門檻，戰鬥特效多時可調高",
    )
    sp.add_argument("-m", "--max-frames", type=int, default=24, help="最多保留幾張")
    sp.add_argument("--cols", type=int, default=4, help="總覽圖每列幾格")
    sp.set_defaults(func=cmd_record)

    sp = sub.add_parser("sheet", help="從已存的錄製資料夾重做總覽圖")
    sp.add_argument("name", help="錄製名稱")
    sp.add_argument("-m", "--max-frames", type=int, default=36, help="最多幾格")
    sp.add_argument("--cols", type=int, default=6, help="每列幾格")
    sp.add_argument("--start", type=int, default=0, help="從第幾張開始（分批看用）")
    sp.add_argument("--count", type=int, help="這批取幾張，不給表示取到最後")
    sp.set_defaults(func=cmd_sheet)

    sp = sub.add_parser("scan", help="掃描整段錄製，找出出現指定模板的幀")
    sp.add_argument("name", help="錄製名稱")
    sp.add_argument("template", help="要找的模板")
    sp.add_argument("-t", "--threshold", type=float, default=0.85)
    sp.add_argument("-v", "--verbose", action="store_true", help="連沒命中的也印分數")
    sp.add_argument(
        "--absent", action="store_true",
        help="反向列出沒有這個模板的幀，用來挑出非戰鬥畫面",
    )
    sp.set_defaults(func=cmd_scan)

    sp = sub.add_parser("clean", help="清掉截圖與錄製（samples/ 會保留）")
    sp.add_argument("--yes", dest="dry_run", action="store_false",
                    help="實際刪除；不給這個參數只會試算")
    sp.add_argument("--all", action="store_true", help="連 assistant.log 一起清")
    sp.set_defaults(func=cmd_clean, dry_run=True)

    sp = sub.add_parser("selftest", help="用 samples/ 的實機畫面驗證規則沒被改壞")
    sp.add_argument("-t", "--task", help="腳本名稱")
    sp.set_defaults(func=cmd_selftest)

    sp = sub.add_parser("explain", help="說明當前畫面會觸發哪條規則")
    sp.add_argument("-t", "--task", help="腳本名稱")
    sp.add_argument("--source", help="改用指定截圖判斷，不抓即時畫面")
    sp.set_defaults(func=cmd_explain)

    sp = sub.add_parser("find", help="測試模板比對")
    sp.add_argument("template", help="模板名稱（templates/ 下的檔名，不含副檔名）")
    sp.add_argument("-t", "--threshold", type=float, default=0.85)
    sp.add_argument("-s", "--save", action="store_true", help="輸出標註圖")
    sp.add_argument(
        "--source", help="改用指定截圖比對，不抓即時畫面（可用錄製的幀名）",
    )
    sp.set_defaults(func=cmd_find)

    sp = sub.add_parser("crop", help="從截圖裁出模板")
    sp.add_argument("source", help="logs/shots/ 下的截圖名稱（不含副檔名）")
    sp.add_argument("x", type=int)
    sp.add_argument("y", type=int)
    sp.add_argument("w", type=int)
    sp.add_argument("h", type=int)
    sp.add_argument("name", help="要存成的模板名稱")
    sp.set_defaults(func=cmd_crop)

    sp = sub.add_parser("text", help="用內建 OCR 讀某塊區域的文字（調 log_text 用）")
    sp.add_argument("source", nargs="?", help="截圖名稱，省略則抓當前畫面")
    sp.add_argument("region", nargs="*", type=int, metavar="x y w h",
                    help="要讀的區域，省略則讀整張")
    sp.add_argument("--scale", type=int, default=3, help="放大倍率，預設 3")
    sp.add_argument("--binary", type=int, default=None,
                    help="亮度門檻，給了就先轉成黑字白底（美術字需要）")
    sp.add_argument("--trim-right", type=int, default=0,
                    help="找到文字右端後往左扣掉幾 px（用來切掉標題的「·難度」）")
    sp.set_defaults(func=cmd_text)

    sp = sub.add_parser("tap", help="手動點擊")
    sp.add_argument("x", type=int)
    sp.add_argument("y", type=int)
    sp.set_defaults(func=cmd_tap)

    sub.add_parser("gui", help="開圖形介面（不帶參數執行時也是這個）"
                   ).set_defaults(func=cmd_gui)

    sp = sub.add_parser("run", help="執行腳本")
    sp.add_argument("-t", "--task", help="腳本名稱")
    sp.add_argument("-n", "--repeat", type=int, help="重複次數，0 表示不限")
    sp.add_argument(
        "--dry-run", action="store_true",
        help="只判斷規則、不送出任何點擊，用來驗證流程",
    )
    sp.add_argument(
        "--once", action="store_true",
        help="只跑一輪就結束，忽略 config 的每日排程",
    )
    sp.set_defaults(func=cmd_run)

    return p


def _pause() -> None:
    """雙擊執行時先停住，讓人看得到訊息。"""
    try:
        input("\n按 Enter 關閉視窗 ...")
    except (EOFError, KeyboardInterrupt):
        pass


def main() -> int:
    argv = sys.argv[1:]

    # 清掉上次更新留下的 `.old`。⚠ 只能在下一次啟動刪，換檔當下那個檔案還在執行。
    try:
        from core import updater
        updater.cleanup()
        # 清掉上次被強制結束時留下的解壓目錄。
        updater.sweep_temp()
    except Exception:
        pass                    # 清不掉不影響功能

    # 沒有參數就開圖形介面，帶參數走命令列。
    if not argv:
        # 未打包時 `python main.py` 有主控台可以藏；打包版是 --windowed，沒有主控台。
        hidden = logger.hide_console()
        code = cmd_gui(None)
        if code and hidden:
            logger.show_console()    # 失敗訊息要看得到
        return code

    # 命令列模式：--windowed 的 stdout 是 None，借用呼叫者的主控台。
    # ⚠ 命令列沒有視窗會接手，啟動畫面當場關閉。
    splash.close()
    logger.attach_console()
    # 打包版的視窗標題預設是執行檔路徑
    logger.set_console_title(f"杖劍傳說助手 v{VERSION}")

    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (AdbError, ConfigError, ScriptError) as e:
        # 這些例外的訊息本身就是給使用者看的
        print(f"\n[錯誤] {e}")
        return 1
    except FileNotFoundError as e:
        print(f"\n[錯誤] {e}")
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
