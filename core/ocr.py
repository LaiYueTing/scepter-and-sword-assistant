"""用 Windows 內建的 OCR 讀畫面上的文字。

用在「內容會一直增加」的欄位——副本名稱、難度就是。這種欄位用模板判斷的話，
每出一個新副本都要手動裁一張圖，而且只認得裁過的那幾張。

⚠ 只用來寫紀錄，不要拿去做主流程判斷：每次要開一個 PowerShell（約 1 秒），
  而且美術字讀不穩。判斷該不該動作一律交給模板比對。

兩個實作選擇：

  用 OS 內建而不是 Python 套件——不必安裝、不必打包，也就沒有 PyInstaller
  相依風險。Windows 11 已內建 zh-Hant-TW 辨識器。

  PowerShell 腳本內嵌成字串、用 -EncodedCommand（base64 的 UTF-16LE）傳，
  而不是放一個 .ps1：省掉一個要打包的檔案，也繞過檔案編碼——外部 .ps1 必須存成
  「UTF-8 帶 BOM」，否則 PowerShell 5.1 會當成 cp950 讀而整個語法錯誤。
"""
from __future__ import annotations

import base64
import subprocess
import tempfile
from pathlib import Path

import cv2
import numpy as np

from core import logger

# 名稱要和 logger._MODULES 的鍵一致，不能用 __name__（那會是 core.ocr，
# 對照表對不上，紀錄就露出英文模組名，欄位寬度也跟著歪掉）。
log = logger.get("ocr")

Region = tuple[int, int, int, int]

# 供 -EncodedCommand 使用的腳本本體。
#
# WinRT 的非同步方法在 PowerShell 5.1 沒有 await 可用，要自己把
# IAsyncOperation 轉成 .NET Task 再等它完成，所以有那段反射。
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
    # 中文辨識結果的詞之間會被塞空白，接回去才是原本的字串
    ($line.Words | ForEach-Object { $_.Text }) -join ''
}
"""

_unavailable = False        # 系統沒有辨識器時只抱怨一次，之後靜靜跳過


def _prepare(
    screen: np.ndarray,
    region: Region | None,
    scale: int,
    binary: int | None,
    trim_right: int = 0,
) -> np.ndarray:
    """裁切、（必要時）從右端修掉一段、二值化、放大。

    三個前處理都是必須的，參數也都是實測調出來的：

      scale       720x1280 上的字太小，原尺寸幾乎讀不到（x2 讀成「亞本獎勵」、
                  x4 才讀對「惡夢副本獎勵」）。
      binary      給亮度門檻時轉成「黑字白底」。白色美術字描黑邊又疊在場景圖上
                  的標題非這樣不可（直接讀是「月殿·惡歹」，門檻 210 加放大
                  3 倍才讀出「月之宮殿」）。
      trim_right  只要標題的前半段。標題是「名稱·難度」，右半那段最難讀（會被
                  讀成一個雜字）；難度固定兩個字，「·難度」的寬度就是常數，
                  所以**先找到文字右端、再往左扣掉那個常數**。錨定右端而不是
                  寫死右邊界——標題置中，名稱長度一變左右兩端都會移動。
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
    """讀出區域內的文字，多行會用空白接起來。讀不到就回傳空字串。

    讀不到一律回空字串而不是拋錯：這是「順手記一筆」的功能，
    不該因為它失敗就中斷整個流程。
    """
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
