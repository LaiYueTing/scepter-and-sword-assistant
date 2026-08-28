"""就地修改 config.yaml 的值，保留註解與排版。

不能用 `yaml.safe_load` + `yaml.dump` 往返：那會把整份註解洗掉，而這份設定檔的
註解就是使用者的說明書（每個開關在講什麼、埠號去哪裡查、為什麼半夜要開
accept_with_partners）。洗掉之後，GUI 省下的那點力氣遠遠不划算。

只支援這份設定檔實際用得到的形狀：巢狀對映，加上一層「以 name 識別」的腳本
清單。路徑寫成 tuple，例如：

    ("device", "serial")            device 底下的 serial
    ("options", "claim_reward")     開關
    ("tasks", "raid", "enabled")    tasks 清單裡 name 為 raid 的那一項
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# 「key:」或「- key:」開頭的行。值與行尾註解都留在 rest 裡自己再切。
_LINE = re.compile(
    r"^(?P<indent> *)(?P<dash>-\s+)?(?P<key>[A-Za-z_][A-Za-z0-9_]*)"
    r"\s*:(?P<sep> ?)(?P<rest>.*)$"
)

# 不用加引號就能安全寫出的純量。時間「08:00」不在此列是刻意的——YAML 1.1 會把
# 它讀成六十進位數字 480，一定要引號包起來。
_PLAIN = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.\-]*$")


@dataclass
class _Leaf:
    line: int        # 行號（0 起算）
    value_at: int    # 值在該行的起始欄，替換時從這裡切開


@dataclass
class _Block:
    last: int        # 這個容器最後一個成員的行號
    col: int         # 成員的縮排欄位


def _fmt_scalar(value: Any) -> str:
    if isinstance(value, bool):          # 要排在 int 前面，bool 是 int 的子類
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = "" if value is None else str(value)
    return text if _PLAIN.match(text) else '"' + text.replace('"', '\\"') + '"'


def _fmt(value: Any) -> str:
    """把 Python 值寫成 YAML 的行內表示。

    清單一律用流式（`["12:30", "21:00"]`）。展開成多行的話，改動就會增減行數，
    後面所有行號跟著位移——為了兩三個時間值不值得。
    """
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_fmt_scalar(v) for v in value) + "]"
    return _fmt_scalar(value)


def _split_comment(rest: str) -> tuple[str, str]:
    """把「值 + 行尾註解」切開。值裡不會有 #，這份設定檔沒有那種內容。"""
    idx = rest.find("#")
    if idx < 0:
        return rest, ""
    return rest[:idx], rest[idx:]


def _opens_block(lines: list[str], i: int, col: int) -> bool:
    """`key:` 後面沒有值時，判斷它是「容器」還是「空值的純量」。

    ⚠ 這兩者在 YAML 裡長得一模一樣，只能看下一個有內容的行縮排得比它深不深：

        device:          ← 容器，下一行更深
          serial:        ← 空值純量，下一行同深（host 也在第 2 欄）
          host: 192.168.1.108

    分不出來的後果是「改不到、還會重複新增」：`serial` 被當成容器登記，
    `leaves` 裡就沒有它，於是每改一次 serial 就往 device 區段末尾多插一行
    `serial: ""`——YAML 的重複鍵是後者覆蓋前者，所以行為看起來沒錯，
    但設定檔會愈長愈髒。
    """
    for line in lines[i + 1:]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        return len(line) - len(line.lstrip()) > col
    return False        # 檔案最後一行，後面沒有成員，那就是空值


def scan(lines: list[str]) -> tuple[dict[tuple, _Leaf], dict[tuple, _Block]]:
    """建立「路徑 → 位置」索引，回傳（葉節點, 容器）。

    容器是「冒號後面沒有值」的鍵，記下它最後一個成員在哪，才知道要新增的項目
    該插在哪一行。
    """
    leaves: dict[tuple, _Leaf] = {}
    blocks: dict[tuple, _Block] = {}
    stack: list[tuple[int, str]] = []       # [(成員縮排欄, 名稱)]

    for i, line in enumerate(lines):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = _LINE.match(line)
        if not m:
            continue

        indent = len(m["indent"])
        dash = m["dash"] or ""
        col = indent + len(dash)
        key = m["key"]
        value, _ = _split_comment(m["rest"])
        value = value.strip()

        if dash:
            # 清單項的第一個鍵就在 dash 那一行。項目容器用 dash 的縮排登記，
            # 比成員淺，成員才不會把自己的容器彈掉。
            while stack and stack[-1][0] >= indent:
                stack.pop()
            parent = tuple(n for _, n in stack)
            # 以 name 當識別；萬一第一個鍵不是 name 就退回序號，至少不會錯位。
            ident = value if key == "name" else f"[{i}]"
            stack.append((indent, ident))
            blocks[parent + (ident,)] = _Block(last=i, col=col)
        else:
            # 退回這個鍵所屬的層：同縮排或更深的容器都已經結束了
            while stack and stack[-1][0] >= col:
                stack.pop()

        path = tuple(n for _, n in stack) + (key,)

        # 這個成員讓所有祖先容器的「最後一行」往後推
        for depth in range(1, len(stack) + 1):
            anc = tuple(n for _, n in stack[:depth])
            if anc in blocks:
                blocks[anc].last = i

        if value == "" and not dash and _opens_block(lines, i, col):
            blocks[path] = _Block(last=i, col=col + 2)
            stack.append((col, key))
        else:
            leaves[path] = _Leaf(line=i, value_at=len(m["indent"]) + len(dash)
                                 + len(key) + 1 + len(m["sep"]))

    return leaves, blocks


def _replace(line: str, leaf: _Leaf, value: Any) -> str:
    """換掉一行裡的值，盡量讓行尾註解留在原本的欄位上。

    註解是對齊的（`daily_at: "08:00"          # 副本次數每天早上 08:00 重置`），
    值變短就補回空白，變長才擠掉——不然改一個開關就會把整段註解弄歪。
    """
    head, rest = line[:leaf.value_at], line[leaf.value_at:]
    # 原本就是空值（`serial:`）時冒號後面沒有那個空格，直接接上去會寫成
    # `serial:"auto"`——YAML 解不出來。
    if head.endswith(":"):
        head += " "
    old_value, comment = _split_comment(rest)
    new_value = _fmt(value)
    if not comment:
        return head + new_value
    at = leaf.value_at + len(old_value)          # 註解原本在第幾欄
    pad = max(1, at - (leaf.value_at + len(new_value)))
    return head + new_value + " " * pad + comment


def apply(text: str, changes: dict[tuple, Any]) -> str:
    """把一批改動套用到設定檔文字上，回傳新的內容。

    路徑不存在就補一筆到父容器末尾（使用者可能刪過整段設定）；連父容器都沒有
    就在檔尾補一段。插入從後往前做，否則先插的那筆會讓後面的行號全部位移。
    """
    lines = text.splitlines()
    leaves, blocks = scan(lines)

    inserts: list[tuple[tuple, Any]] = []
    for path, value in changes.items():
        leaf = leaves.get(path)
        if leaf is None:
            inserts.append((path, value))
        else:
            lines[leaf.line] = _replace(lines[leaf.line], leaf, value)

    def sort_key(item: tuple[tuple, Any]) -> int:
        parent = blocks.get(item[0][:-1])
        return parent.last if parent else len(lines)

    for path, value in sorted(inserts, key=sort_key, reverse=True):
        parent = blocks.get(path[:-1])
        entry = f"{path[-1]}: {_fmt(value)}"
        if parent is None:
            lines.extend(["", f"{path[-2]}:" if len(path) > 1 else "",
                          f"  {entry}"])
        else:
            lines.insert(parent.last + 1, " " * parent.col + entry)

    return "\n".join(lines) + "\n"


def save(path: Path, changes: dict[tuple, Any]) -> None:
    """把改動寫回設定檔，沿用原檔的換行慣例。

    ⚠ 一定要自己指定 newline。Windows 上 `write_text` 預設會把 \\n 轉成 \\r\\n，
      而原檔若本來就是 \\r\\n，就會變成 \\r\\r\\n——每行之間多一個空行。
    """
    raw = path.read_bytes()
    newline = "\r\n" if b"\r\n" in raw else "\n"
    text = raw.decode("utf-8")
    result = apply(text.replace("\r\n", "\n"), changes)
    with open(path, "w", encoding="utf-8", newline=newline) as f:
        f.write(result)
