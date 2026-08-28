/**
 * 掃過**全部**背景主題 × 深淺兩套，確認每一組文字／表面的對比都還在。
 *
 *   node tools/check-contrast.mjs
 *
 * 為什麼需要這支，有兩個各自獨立的理由：
 *
 *   1. **換色相不等於不動對比。** 相對亮度不是只看 L——同樣 L=55% 的黃色比藍色亮
 *      得多。「理論上不會變」要拿數字驗。
 *   2. **卡片是半透明的**，所以字真正落在的底是「卡片色 ＋ 透上來的漸層」，不是
 *      `--bg-2`。拿 `--bg-2` 去量會得到一組好看但和畫面無關的數字。
 *
 * ⚠ **驗的是 `appearanceFor()` 本尊**，不是在這裡重算一次。兩邊的公式只要差一點，
 *   量出來的數字就和使用者看到的畫面對不起來，而那種落差極難察覺。
 *
 * ⚠ 出現任何 FAIL 就不要出貨。使用者連續三次回報「字看不清楚」，那幾輪的成果全部
 *   壓在這些數字上。
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

/** 卡片上的小字。半透明時要拿合成後的底去量，那才是畫面上真正發生的事。 */
const ON_CARD = ['--text-0', '--text-1', '--text-2', '--accent-text', '--green', '--amber', '--red']
/** 面板（`--bg-1`）上的字。那一層不透明，直接量。 */
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
     * 主要按鈕上的字。驗的是 `--accent-on`，不是白字——主色刻意不為了撐住白字而
     * 被壓暗（那會讓黃色系主題整片變土色），改成換字色。
     */
    note(`${tag} --accent-on / 主色`, cr(parse(v['--accent-on']), parse(v['--accent'])), AA, t.name)

    /*
     * ⚠ **對比夠不代表階層對。** 文字為了壓在半透明卡片上被拉亮，拉過頭就會和
     *   `--text-1` 一樣亮——那時候「主要／次要／補充」三層在畫面上分不出來，而
     *   使用者的抱怨會是「很多字都是灰色」而不是「看不清楚」。這兩種毛病的症狀
     *   一樣，修法相反，所以兩個都要驗。
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
