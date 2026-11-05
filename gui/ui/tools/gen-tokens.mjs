/**
 * 產生 `src/styles/tokens.css`：JS 執行之前的預設配色，避免開視窗時閃一下沒有顏色的畫面。
 *
 *   node tools/gen-tokens.mjs
 *
 * ⚠ 不要手改 tokens.css，要改顏色請改 `palette.js` 的階梯再重跑。
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
 * ⚠ 這個檔案是產生出來的，不要手改。
 *   來源：\`src/data/palette.js\` ＋ \`tools/gen-tokens.mjs\`（\`node tools/gen-tokens.mjs\`）
 *
 * JS 執行之前的預設配色，色相 ${BASE_HUE}（藏藍）。選了背景主題之後由 \`applyAppearance()\` 覆蓋。
 *
 * ⚠ 每一個顏色都在深淺兩套各定義一次。
 * ⚠ 可讀性由 \`tools/check-contrast.mjs\` 檢查：175 組主題 × 深淺兩套，對比 ≥ 4.5。
 */

${block(":root,\n:root[data-theme='dark']", paletteFor(null, true), shared + '\n  color-scheme: dark;')}

${block(":root[data-theme='light']", paletteFor(null, false), shared + '\n  color-scheme: light;')}
`

writeFileSync(resolve(here, '../src/styles/tokens.css'), out, 'utf8')
console.log('已產生 src/styles/tokens.css')
