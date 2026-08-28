# -*- coding: utf-8 -*-
"""core/confedit.py 的回歸測試：

    python tests/test_confedit.py

改設定檔那條路沒有實機畫面可驗，selftest 也涵蓋不到（那支是驗規則的），
所以這裡自己守。重點在「空值的鍵」——`serial:` 這種冒號後面沒東西的寫法，
和「容器」在 YAML 裡長得一模一樣，分不出來就會每改一次往設定檔多插一行。
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ⚠ **測試不能寫進真正的 assistant.log。** 那是使用者用來監督執行狀況的檔案，
#   混進假的排程與假的下載失敗比沒有紀錄更糟。要在 import core 之前設定。
os.environ.setdefault("SSA_LOG_DIR", tempfile.mkdtemp(prefix="ssa-test-log-"))

import yaml
from core import confedit

SRC = """\
# 設定檔開頭的說明
device:
  # 模擬器在實體機，助手在虛擬機
  serial:
  host: 192.168.1.108
  # ADB 調試埠
  port: 16480

tasks:
  - name: dungeon
    enabled: true
    daily_at: "08:00"          # 對齊的行尾註解
    repeat: 0

  - name: raid
    enabled: true
    daily_at: ["12:30", "21:00"]
    repeat: 1

options:
  claim_reward: true
  buy_counts: 1
"""

def check(name, cond):
    print(("  [通過] " if cond else "  [失敗] ") + name)
    return cond

ok = True
print("=== 1. 改空值的 serial（原本的 bug）===")
out = confedit.apply(SRC, {("device", "serial"): "auto"})
data = yaml.safe_load(out)
ok &= check("serial 變成 auto", data["device"]["serial"] == "auto")
ok &= check("沒有多出重複的行", out.count("serial") == 1)
ok &= check("行數不變", len(out.splitlines()) == len(SRC.splitlines()))
ok &= check("host 沒被動到", data["device"]["host"] == "192.168.1.108")
ok &= check("port 沒被動到", data["device"]["port"] == 16480)

print("=== 2. 空值改成空字串（GUI 選網路裝置時會這樣送）===")
out2 = confedit.apply(SRC, {("device", "serial"): ""})
data2 = yaml.safe_load(out2)
ok &= check("serial 是空的", not data2["device"]["serial"])
ok &= check("沒有多出重複的行", out2.count("serial") == 1)

print("=== 3. 一次改三個（GUI 選裝置的實際情況）===")
out3 = confedit.apply(SRC, {
    ("device", "serial"): "",
    ("device", "host"): "192.168.1.50",
    ("device", "port"): 7555,
})
data3 = yaml.safe_load(out3)
ok &= check("host 改了", data3["device"]["host"] == "192.168.1.50")
ok &= check("port 改了", data3["device"]["port"] == 7555)
ok &= check("行數不變", len(out3.splitlines()) == len(SRC.splitlines()))

print("=== 4. 註解與排版都在 ===")
ok &= check("註解行數不變",
            sum(1 for l in out3.splitlines() if l.lstrip().startswith("#"))
            == sum(1 for l in SRC.splitlines() if l.lstrip().startswith("#")))
out4 = confedit.apply(SRC, {("tasks", "dungeon", "repeat"): 3})
ok &= check("行尾註解留在原欄位",
            'daily_at: "08:00"          # 對齊的行尾註解' in out4)
ok &= check("清單項改得到", yaml.safe_load(out4)["tasks"][0]["repeat"] == 3)

print("=== 5. 時間值一定要有引號（YAML 1.1 會把 08:00 讀成 480）===")
out5 = confedit.apply(SRC, {("tasks", "raid", "daily_at"): ["09:30"]})
ok &= check("讀回來還是字串",
            yaml.safe_load(out5)["tasks"][1]["daily_at"] == ["09:30"])

print("=== 6. 真的不存在的鍵才新增 ===")
out6 = confedit.apply(SRC, {("options", "claim_daily_reward"): True})
ok &= check("新增了一行", yaml.safe_load(out6)["options"]["claim_daily_reward"] is True)
ok &= check("多一行", len(out6.splitlines()) == len(SRC.splitlines()) + 1)

print("\n" + ("全部通過" if ok else "有失敗項目"))
sys.exit(0 if ok else 1)
