/**
 * 確認每一個顏色 token 都是 naive-ui（seemly）解析得了的格式。
 *
 *   node tools/check-tokens.mjs
 *
 * seemly 接受 `#hex`、`rgb(r, g, b)`、`rgba(r, g, b, a)`、`hsl(h, s%, l%)`，不接受空白分隔的語法：
 *
 *     hsl(221 70% 62%)、rgb(91 108 255)、rgb(91 108 255 / 0.5) → 丟例外
 *
 * 丟例外時，需要推導色階的元件（NCheckbox、NInput、NInputNumber、NDropdown）會 render 成空的。
 */
import { rgba } from 'seemly'
import { BG_THEMES, appearanceFor } from '../src/data/gradients.js'

/** 這些 token 是漸層或陰影，不是單一顏色。 */
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
    // 這兩個只用於 CSS，格式規則相同
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
