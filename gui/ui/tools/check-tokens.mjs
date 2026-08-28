/**
 * 確認每一個顏色 token 都是 **naive-ui 解得動**的格式。
 *
 *   node tools/check-tokens.mjs
 *
 * ## 為什麼需要一支專門驗格式的
 *
 * naive-ui 用 seemly 把顏色解析出來，再推導 hover / pressed / disabled 的色階。
 * seemly 認得 `#hex`、`rgb(r, g, b)`、`rgba(r, g, b, a)`、`hsl(h, s%, l%)`，
 * 但**解不了 CSS 新語法的空白分隔版**：
 *
 *     hsl(221 70% 62%)      → 丟例外
 *     rgb(91 108 255)       → 丟例外
 *     rgb(91 108 255 / 0.5) → 丟例外
 *
 * 而這個例外的症狀**極度誤導**：畫面不會整個壞掉，只有需要推導色階的元件
 * （`NCheckbox`、`NInput`、`NInputNumber`、`NDropdown`）靜靜地 render 成空的
 * `<!---->`，按鈕卻好好的。實際看到的是三個看起來毫不相干的毛病：
 *
 *   - 玩法設定的勾選框「全部不見了」
 *   - 裝置面板的欄位錯位（輸入框沒 render，grid 於是塌掉）
 *   - 紀錄的右鍵選單按了沒反應
 *
 * ⚠ 用眼睛是驗不出來的——**顏色本身是對的**，錯的只有寫法。所以這支要跟著
 *   `check-contrast.mjs` 一起跑。
 */
import { rgba } from 'seemly'
import { BG_THEMES, appearanceFor } from '../src/data/gradients.js'

/** 這些 token 是漸層或陰影，本來就不是單一顏色，naive-ui 也不會拿去推色階。 */
const NOT_A_COLOR = new Set(['--card-hi', '--shadow-card', '--shadow-pop', '--accent-grad'])

const bad = []
let checked = 0

for (const isDark of [true, false]) {
  for (const t of BG_THEMES) {
    const a = appearanceFor(t.id, isDark)
    for (const [name, value] of Object.entries(a.vars)) {
      if (NOT_A_COLOR.has(name)) continue
      checked++
      try {
        rgba(value)
      } catch (e) {
        bad.push(`${isDark ? '深' : '淺'} ${t.name}　${name}: ${value}`)
      }
    }
    // 這兩個只餵給 CSS，但同一份規則寫兩種格式，總有一天會有人把它接到 naive-ui 上
    for (const [name, value] of [['cardBg', a.cardBg], ['appBg', a.appBg]]) {
      if (!value || name === 'appBg') continue
      checked++
      try {
        rgba(value)
      } catch (e) {
        bad.push(`${isDark ? '深' : '淺'} ${t.name}　${name}: ${value}`)
      }
    }
  }
}

console.log(`檢查了 ${checked} 個顏色值（${BG_THEMES.length} 組主題 × 深淺兩套）`)
if (bad.length) {
  console.log(`\n${bad.length} 個 naive-ui 解不動：`)
  for (const b of bad.slice(0, 10)) console.log('  ' + b)
  console.log('\n改成 #hex 或 rgba(r, g, b, a)。')
  process.exit(1)
}
console.log('全部通過。')
