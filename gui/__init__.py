"""圖形介面：pywebview 的外殼 ＋ Vue 前端。

**這只是另一張臉**——連線、規則引擎、排程全部沿用 `core/` 底下同一份程式，
這裡不重新實作任何判斷邏輯。

    app.py       視窗外殼：建視窗、系統匣、把方法表交給 pywebview
    api.py       前端叫得到的方法表，一個方法一件事
    bridge.py    把 logging 與狀態接到通道上
    runner.py    在背景執行緒跑排程，狀態回報給介面
    tray.py      系統匣圖示與選單
    ui/          前端原始碼（Vue 3 + naive-ui + Tailwind）
    web/         `npm run build` 的產物，會被打包進 EXE
"""
