import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwind from '@tailwindcss/vite'

const here = dirname(fileURLToPath(import.meta.url))

/**
 * 把介面編成純網頁資源，給 pywebview 載入（`npm run build`）。
 *
 * ⚠ **`base: './'` 是必要的。** pywebview 是用 `file://` 載入的，絕對路徑一律 404
 *   ——而那個失敗的樣子是「視窗開起來、畫面全白」，不會有任何錯誤訊息。
 *
 * ⚠ **輸出檔名固定、不帶雜湊。** `.spec` 是用 `--add-data` 帶整個資料夾進 EXE 的，
 *   帶雜湊只會讓每次建置都留下一份舊檔案；`emptyOutDir` 會清掉，但固定檔名讀起來
 *   也單純。
 */
export default defineConfig({
  root: here,
  base: './',
  resolve: { alias: { '@': resolve(here, 'src') } },
  plugins: [vue(), tailwind()],
  build: {
    outDir: resolve(here, '../web'),
    emptyOutDir: true,
    assetsInlineLimit: 8192,
    rollupOptions: {
      input: { index: resolve(here, 'index.html') },
      output: {
        entryFileNames: 'app.js',
        chunkFileNames: 'app-[name].js',
        assetFileNames: 'app.[ext]'
      }
    }
  }
})
