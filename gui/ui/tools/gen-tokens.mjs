/**
 * 產生 `src/styles/tokens.css`——**JS 還沒跑起來之前**的那一套顏色。
 *
 *   node tools/gen-tokens.mjs
 *
 * 為什麼需要一份靜態的：整套配色是 `palette.js` 在執行時算出來的，而在那之前
 * 瀏覽器已經畫過一次了。少了這份靜態預設，開窗那一瞬間會閃一下沒有顏色的畫面。
 *
 * ⚠ **不要手改 tokens.css。** 它是產物，改了下次重新產生就沒了；而手改的那個值和
 *   `palette.js` 算出來的不一致時，症狀是「開窗閃一下，顏色跟穩定之後不一樣」，
 *   非常難聯想到這裡。要改顏色請改 `palette.js` 的階梯再重跑這支。
 */
import { writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { paletteFor, BASE_HUE } from '../src/data/palette.js'

const here = dirname(fileURLToPath(import.meta.url))

function block(selector, vars, extra) {
  const lines = Object.entries(vars).map(([k, v]) => `  ${k}: ${v};`)
  return `${selector} {\n${lines.join('\n')}\n${extra}\n}`
}

const shared = [
  '  --radius-card: 14px;',
  '  --radius-input: 9px;',
  '  --app-bg: var(--bg-0);'
].join('\n')

const out = `/*
 * ⚠ **這個檔案是產生出來的，不要手改。**
 *   來源：\`src/data/palette.js\` ＋ \`tools/gen-tokens.mjs\`（\`node tools/gen-tokens.mjs\`）
 *
 * 這裡放的是「JS 還沒跑之前」的預設配色，色相 ${BASE_HUE}（Telegram-RMA 那套藏藍）。
 * 選了背景主題之後，\`applyAppearance()\` 會用 inline 變數把整套蓋掉——面板、卡片、
 * 框線、文字全部跟著那個主題的色相走，不是只換背景。
 *
 * ⚠ 每一個顏色都在深淺兩套各定義一次。只定義一邊、另一邊靠繼承的話，切過去會留著
 *   上一套的殘留色，而且往往只在某個狀態下才看得出來。
 *
 * ⚠ 這些數字的可讀性由 \`tools/check-contrast.mjs\` 守著：175 組主題 × 深淺兩套，
 *   每一組文字／表面的對比都要 ≥ 4.5。改階梯之後一定要重跑那支。
 */

${block(":root,\n:root[data-theme='dark']", paletteFor(null, true), shared + '\n  color-scheme: dark;')}

${block(":root[data-theme='light']", paletteFor(null, false), shared + '\n  color-scheme: light;')}
`

writeFileSync(resolve(here, '../src/styles/tokens.css'), out, 'utf8')
console.log('已產生 src/styles/tokens.css')
