import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwind from '@tailwindcss/vite'

const here = dirname(fileURLToPath(import.meta.url))

/**
 * 把介面編成純網頁資源，給 pywebview 載入（`npm run build`）。
 *
 * ⚠ `base: './'`：pywebview 用 `file://` 載入，絕對路徑會 404。
 * ⚠ 輸出檔名固定、不帶雜湊。
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
