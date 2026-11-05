/**
 * 檢查全部背景主題 × 深淺兩套的文字與表面對比，出現 FAIL 不可發布。
 *
 *   node tools/check-contrast.mjs
 *
 * ⚠ 驗的是 `appearanceFor()` 本身，不在這裡重算。半透明卡片要用合成後的底色量。
 */
import { BG_THEMES, appearanceFor } from '../src/data/gradients.js'
import { luminance, rgbToHsl } from '../src/data/palette.js'

const AA = 4.5

function parse(css) {
  if (css.startsWith('#')) {
    const h = css.slice(1)
    return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16))
  }
  const m = css.match(/rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)/)
  return [+m[1], +m[2], +m[3]]
}
function cr(a, b) {
  const [la, lb] = [luminance(a), luminance(b)]
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05)
}
const lightnessOf = (css) => rgbToHsl(parse(css))[2]

/** 卡片上的小字，用合成後的底色量。 */
const ON_CARD = ['--text-0', '--text-1', '--text-2', '--accent-text', '--green', '--amber', '--red']
/** 面板（`--bg-1`）上的字。 */
const ON_PANEL = ['--text-0', '--text-1', '--text-2']

const worst = {}
const fails = []
const note = (key, v, min, theme) => {
  if (!worst[key] || v < worst[key].v) worst[key] = { v, min, theme }
  if (v < min) fails.push(`${key}  ${v.toFixed(2)} < ${min}  ← ${theme}`)
}

for (const isDark of [true, false]) {
  const tag = isDark ? '深' : '淺'
  for (const t of BG_THEMES) {
    const a = appearanceFor(t.id, isDark)
    const v = a.vars
    const cardBg = a.composite || parse(v['--bg-2'])
    const panelBg = parse(v['--bg-1'])

    for (const k of ON_CARD) note(`${tag} ${k} / 卡片`, cr(parse(v[k]), cardBg), AA, t.name)
    for (const k of ON_PANEL) note(`${tag} ${k} / 面板`, cr(parse(v[k]), panelBg), AA, t.name)

    note(`${tag} --border / 面板`, cr(parse(v['--border']), panelBg), 1.3, t.name)

    /*
     * 主要按鈕上的字，驗 `--accent-on`。
     */
    note(`${tag} --accent-on / 主色`, cr(parse(v['--accent-on']), parse(v['--accent'])), AA, t.name)

    /*
     * ⚠ 對比夠不代表階層對：次要文字不可被拉亮到和 `--text-1` 一樣。
     */
    const gap = isDark
      ? lightnessOf(v['--text-1']) - lightnessOf(v['--text-2'])
      : lightnessOf(v['--text-2']) - lightnessOf(v['--text-1'])
    note(`${tag} text-1 與 text-2 的明度差`, gap, 3, t.name)
  }
}

console.log(`掃過 ${BG_THEMES.length} 組主題 × 深淺兩套\n`)
console.log('每一項的最差情況：')
for (const [k, { v, min, theme }] of Object.entries(worst)) {
  const mark = v < min ? 'FAIL' : ' ok '
  console.log(`  [${mark}] ${k.padEnd(30)} ${v.toFixed(2)}  （門檻 ${min}）最差：${theme}`)
}
if (fails.length) {
  console.log(`\n${fails.length} 項不合格：`)
  for (const f of fails.slice(0, 20)) console.log('  ' + f)
  process.exit(1)
}
console.log('\n全部通過。')
