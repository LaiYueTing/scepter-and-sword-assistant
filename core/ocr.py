"""用 Windows 內建的 OCR 讀畫面文字（zh-Hant-TW），不需要安裝或打包其他套件。

⚠ 只用來寫紀錄與讀純數字：每次要開一個 PowerShell（約 1 秒），美術字讀不穩。

PowerShell 腳本內嵌成字串，用 -EncodedCommand（base64 的 UTF-16LE）傳遞，
不受檔案編碼影響（PowerShell 5.1 會把沒有 BOM 的 UTF-8 檔當成 cp950）。
"""
from __future__ import annotations

import base64
import subprocess
import tempfile
from pathlib import Path

import cv2
import numpy as np

from core import logger

# ⚠ 名稱要和 logger._MODULES 的鍵一致，不可用 __name__。
log = logger.get("ocr")

Region = tuple[int, int, int, int]

# 供 -EncodedCommand 使用的腳本本體。
# WinRT 的非同步方法在 PowerShell 5.1 沒有 await，要用反射把 IAsyncOperation 轉成 .NET Task。
_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
Add-Type -AssemblyName System.Runtime.WindowsRuntime | Out-Null

$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and
    $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
})[0]

function Await($operation, $resultType) {
    $task = $asTaskGeneric.MakeGenericMethod($resultType).Invoke($null, @($operation))
    $task.Wait(-1) | Out-Null
    $task.Result
}

# 這些型別要先碰一下才會載入 WinRT 投影
[Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics, ContentType = WindowsRuntime] | Out-Null
[Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
[Windows.Globalization.Language, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null

$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage(
    (New-Object Windows.Globalization.Language -ArgumentList '__LANG__'))
if ($null -eq $engine) { exit 2 }

$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync('__PATH__')) ([Windows.Storage.StorageFile])
$stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
$result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])

foreach ($line in $result.Lines) {
    # 中文辨識結果的詞之間有空白，接回原字串
    ($line.Words | ForEach-Object { $_.Text }) -join ''
}
"""

_unavailable = False        # 系統沒有辨識器時只警告一次


def _prepare(
    screen: np.ndarray,
    region: Region | None,
    scale: int,
    binary: int | None,
    trim_right: int = 0,
) -> np.ndarray:
    """裁切、從右端修掉一段、二值化、放大。

      scale       放大倍率。原尺寸幾乎讀不到（x2「亞本獎勵」、x4「惡夢副本獎勵」）。
      binary      亮度門檻，轉成黑字白底，用於白字描黑邊的標題（門檻 210）。
      trim_right  先找到文字右端，再往左扣掉這個寬度（標題置中，不可寫死右邊界）。
    """
    img = screen
    if region:
        x, y, w, h = region
        img = img[y:y + h, x:x + w]

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    ink = gray >= (binary if binary is not None else 200)

    if trim_right:
        cols = np.flatnonzero(ink.any(axis=0))
        if len(cols):
            edge = int(cols[-1]) - trim_right
            if edge > 0:
                img, ink = img[:, :edge], ink[:, :edge]

    if binary is not None:
        img = np.where(ink, 0, 255).astype(np.uint8)

    h, w = img.shape[:2]
    return cv2.resize(img, (w * scale, h * scale), interpolation=cv2.INTER_CUBIC)


def read(
    screen: np.ndarray,
    region: Region | None = None,
    scale: int = 3,
    binary: int | None = None,
    trim_right: int = 0,
    lang: str = "zh-Hant-TW",
    timeout: float = 25,
) -> str:
    """讀出區域內的文字，多行用空白連接；讀不到就回傳空字串，不拋錯。"""
    global _unavailable
    if _unavailable:
        return ""

    img = _prepare(screen, region, scale, binary, trim_right)
    tmp = Path(tempfile.gettempdir()) / f"stafftale_ocr_{id(img):x}.png"
    try:
        cv2.imencode(".png", img)[1].tofile(str(tmp))
        script = _SCRIPT.replace("__LANG__", lang).replace("__PATH__", str(tmp))
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive",
             "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
            capture_output=True, timeout=timeout,
            # ⚠ --windowed 沒有主控台，不帶 CREATE_NO_WINDOW 每次都會閃一個 PowerShell 視窗。
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if proc.returncode == 2:
            _unavailable = True
            log.warning("系統沒有安裝 %s 的文字辨識器，略過文字辨識", lang)
            return ""
        if proc.returncode != 0:
            log.debug("文字辨識失敗：%s", proc.stderr.decode("utf-8", "ignore")[:200])
            return ""
        lines = proc.stdout.decode("utf-8", "ignore").split()
        return " ".join(lines)
    except (OSError, subprocess.SubprocessError) as e:
        log.debug("文字辨識無法執行：%s", e)
        return ""
    finally:
        tmp.unlink(missing_ok=True)
