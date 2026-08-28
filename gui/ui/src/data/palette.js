/**
 * 從背景主題推導出**整套**配色，不是只換背景。
 *
 * 選了「傳說日落」，該變的不只是底圖——面板、卡片、框線、輸入框、次要文字全都要跟著
 * 那個主題的色相走，否則畫面會變成「一張彩色壁紙配一套灰色介面」，看起來像沒套用成功。
 *
 * ## 為什麼是換色相，不是把卡片做成半透明
 *
 * 半透明讓漸層透上來是最直覺的作法，但**量過就知道不行**：卡片做到 88% 不透明時，
 * 深色的 `--text-2` 在最糟的漸層上只有 **4.24:1**，而 WCAG AA 的小字門檻是 4.5。
 * 再壓下去漸層就看不見了，等於白做。
 *
 * 這裡的作法是 **HSL 上只換 H（色相），S 與 L 走固定的階梯**：
 *
 *   - **L 不動 → 對比度幾乎不動**（相對亮度主要由 L 決定），所以那三輪調出來的
 *     可讀性不會因為換主題而毀掉。
 *   - **H 全部換掉 → 整個介面一起變色**，這正是使用者要的效果。
 *   - 同色相不同 S 只影響「鮮不鮮豔」，剩下那點亮度差由 `verify` 那支腳本掃過
 *     全部 174 組主題確認過（見 `tools/check-contrast.mjs`）。
 *
 * ⚠ **不要改 LADDER 的 L 值。** 那幾個數字是可讀性的來源，不是造型。要讓主題更鮮豔
 *   請調 S，不要調 L。
 */

/* ══════════════════════════════════════════════════════════════════════
   色彩轉換
   ══════════════════════════════════════════════════════════════════════ */

function hexToRgb(hex) {
  const h = hex.replace('#', '')
  const n =
    h.length === 3
      ? h
          .split('')
          .map((c) => c + c)
          .join('')
      : h
  return [0, 2, 4].map((i) => parseInt(n.slice(i, i + 2), 16))
}

export function rgbToHsl([r, g, b]) {
  r /= 255
  g /= 255
  b /= 255
  const max = Math.max(r, g, b)
  const min = Math.min(r, g, b)
  const l = (max + min) / 2
  if (max === min) return [0, 0, l * 100]
  const d = max - min
  const s = l > 0.5 ? d / (2 - max - min) : d / (max + min)
  let h
  if (max === r) h = ((g - b) / d + (g < b ? 6 : 0)) / 6
  else if (max === g) h = ((b - r) / d + 2) / 6
  else h = ((r - g) / d + 4) / 6
  return [h * 360, s * 100, l * 100]
}

/**
 * 把 HSL 寫成 CSS。
 *
 * ⚠ **一定要吐 hex 或 `rgba(r, g, b, a)`，不能吐 `hsl(...)`。** naive-ui 用 seemly
 *   去解析顏色再推導 hover / pressed / disabled 的色階，而 seemly **解不了空白分隔的
 *   `hsl()`**（`hsl(221 70% 62%)` 直接丟例外，逗號版才行）。
 *
 *   而這個例外的症狀極度誤導：畫面不會整個壞掉，只有需要推導色階的那些元件
 *   （`NCheckbox`、`NInput`、`NInputNumber`、`NDropdown`）**靜靜地 render 成空的
 *   `<!---->`**，按鈕卻好好的。實際看到的是「玩法設定的勾選框全部不見了」「裝置面板
 *   的欄位錯位」「右鍵選單按了沒反應」——三個看起來毫不相干的毛病，同一個根因。
 *
 *   `tools/check-tokens.mjs` 就是為了讓這件事不可能再無聲發生。
 */
function hslToCss(h, s, l, alpha) {
  const [r, g, b] = hslToRgb(h, s, l)
  if (alpha === undefined) {
    return '#' + [r, g, b].map((v) => v.toString(16).padStart(2, '0')).join('')
  }
  return `rgba(${r}, ${g}, ${b}, ${(alpha / 100).toFixed(3)})`
}

/** 相對亮度（WCAG）。只給 `tools/check-contrast.mjs` 與這裡的鉗制用。 */
export function luminance([r, g, b]) {
  const f = (c) => {
    c /= 255
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
  }
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)
}

export function hslToRgb(h, s, l) {
  h = ((h % 360) + 360) % 360
  s /= 100
  l /= 100
  const c = (1 - Math.abs(2 * l - 1)) * s
  const x = c * (1 - Math.abs(((h / 60) % 2) - 1))
  const m = l - c / 2
  const seg = [
    [c, x, 0],
    [x, c, 0],
    [0, c, x],
    [0, x, c],
    [x, 0, c],
    [c, 0, x]
  ][Math.floor(h / 60) % 6]
  return seg.map((v) => Math.round((v + m) * 255))
}

/* ══════════════════════════════════════════════════════════════════════
   把明度調到剛好過門檻
   ══════════════════════════════════════════════════════════════════════ */

export function contrast(a, b) {
  const [la, lb] = [luminance(a), luminance(b)]
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05)
}

/**
 * 找出「最接近原本那個 L、又能達到目標對比」的明度。
 *
 * ⚠ **這一步不能省，也不能改用手挑的固定值。** 相對亮度不是只看 L——同樣 L=55%
 *   的黃色比藍色亮得多，所以「L 固定、只換色相」在理論上不影響對比，實際上會。
 *   第一版就是這樣寫的，`tools/check-contrast.mjs` 一跑掃出 **369 項不合格**。
 *
 * ⚠ 二分找的是**最小改動**：深色往上調到剛好過、淺色往下調到剛好過。直接把所有主題
 *   都套最保守的那個值也會過，但那等於讓 174 組主題長得一樣淡。
 *
 * @param {number} h 色相
 * @param {number} s 飽和度
 * @param {number} l0 想要的明度（過得了就原樣回傳）
 * @param {number[]} bg 這個顏色會出現在什麼底上
 * @param {number} target 目標對比
 * @param {boolean} lighten true＝往亮的方向找（深色主題的文字）
 */
/*
 * ⚠ **目標要加一點餘裕。** `hslToCss` 會把 L 四捨五入到小數一位，而二分找到的是
 *   「剛好 4.50」的那個點——輸出時被捨掉一點，量回來就變成 4.45 而不合格。
 *   第一次修完仍有 221 項 FAIL，全部是這種差 0.01～0.05 的。
 */
const MARGIN = 0.15

function fitL(h, s, l0, bg, target0, lighten) {
  const target = target0 + MARGIN
  if (contrast(hslToRgb(h, s, l0), bg) >= target) return l0
  let lo = lighten ? l0 : 0
  let hi = lighten ? 100 : l0
  for (let i = 0; i < 24; i++) {
    const mid = (lo + hi) / 2
    const ok = contrast(hslToRgb(h, s, mid), bg) >= target
    if (lighten) ok ? (hi = mid) : (lo = mid)
    else ok ? (lo = mid) : (hi = mid)
  }
  return lighten ? hi : lo
}

/* ══════════════════════════════════════════════════════════════════════
   階梯：S 與 L 固定，H 由主題決定
   ══════════════════════════════════════════════════════════════════════ */

/*
 * 深色那條梯子的 L 值直接沿用 Telegram-RMA 那套藏藍（使用者指名要那個），
 * 量出來是 8.4 / 12.4 / 16.1 / 21.2，框線 23.9，色相一致在 221。
 *
 * ⚠ `bg2`（卡片）比 `bg1`（面板）**亮**，這是刻意的：卡片要浮在面板上面。
 *   反過來排會讓整個層次感消失。
 */
const DARK = {
  surfaces: [
    ['--bg-0', 45, 8.4],
    ['--bg-1', 45, 12.4],
    ['--bg-2', 46, 16.1],
    ['--bg-3', 44, 21.2]
  ],
  border: ['--border', 40, 26],
  borderSoft: ['--border-soft', 38, 20],
  texts: [
    ['--text-0', 48, 93],
    ['--text-1', 28, 71],
    ['--text-2', 16, 55]
  ],
  // 主色：H 跟著主題，但 S/L 鉗在「白字讀得到」的範圍內
  accent: [70, 62],
  accent2Shift: 28, // 第二個主色往色相環正方向轉這麼多度
  accentText: [78, 74], // 卡片上的小字用，要比按鈕底色亮
  accentDim: [62, 48],
  status: {
    '--green': [58, 48],
    '--amber': [78, 56],
    '--red': [88, 68],
    '--neon': [72, 58]
  }
}

const LIGHT = {
  surfaces: [
    ['--bg-0', 30, 91],
    ['--bg-1', 38, 96.5],
    ['--bg-2', 46, 99.4],
    ['--bg-3', 32, 93.5]
  ],
  border: ['--border', 24, 82],
  borderSoft: ['--border-soft', 22, 88],
  texts: [
    ['--text-0', 42, 9],
    ['--text-1', 24, 27],
    ['--text-2', 15, 41]
  ],
  accent: [64, 40],
  accent2Shift: 28,
  accentText: [66, 36],
  accentDim: [70, 30],
  status: {
    '--green': [72, 27],
    '--amber': [92, 27],
    '--red': [64, 42],
    '--neon': [70, 26]
  }
}

/*
 * 狀態色的色相是**固定的**，不跟著主題轉。
 * ⚠ 綠＝好、黃＝注意、紅＝壞，那是使用者從別的軟體帶過來的認知。跟著主題把「錯誤」
 *   轉成綠色，紀錄面板就再也讀不出哪一行是警告了——主題可以換心情，不能換語意。
 */
const STATUS_HUE = { '--green': 152, '--amber': 42, '--red': 2, '--neon': 168 }

/* ══════════════════════════════════════════════════════════════════════
   從漸層萃取色相
   ══════════════════════════════════════════════════════════════════════ */

/** 抓出漸層字串裡的所有色停。 */
export function stopsOf(css) {
  return (css.match(/#[0-9a-f]{3,8}\b/gi) || []).map(hexToRgb)
}

/** 漸層上最亮與最暗的那一停——毛玻璃疊上去之後，最糟的情況就出在這兩個。 */
export function extremesOf(css) {
  const stops = stopsOf(css)
  if (!stops.length) return null
  let hi = stops[0]
  let lo = stops[0]
  for (const s of stops) {
    if (luminance(s) > luminance(hi)) hi = s
    if (luminance(s) < luminance(lo)) lo = s
  }
  return { hi, lo }
}

/** 兩個顏色照 alpha 混合。`t` 是**前者**的比例。 */
export function mixRgb(a, b, t) {
  return a.map((v, i) => v * t + b[i] * (1 - t))
}

/**
 * 這組漸層「是什麼顏色」。
 *
 * 取**最飽和**的那一停，不是取平均：平均會把互補色抵消成灰（實測「冰火」那種
 * 藍配桃紅的漸層，平均之後色相跑到綠色去，和畫面上看到的完全不像）。
 *
 * ⚠ 純黑到純白那種沒有色相的漸層（`wg40`）要有退路，回傳 null 讓呼叫端沿用預設色相。
 */
export function hueOf(css) {
  const stops = stopsOf(css)
  if (!stops.length) return null
  let best = null
  for (const rgb of stops) {
    const [h, s, l] = rgbToHsl(rgb)
    // 太暗或太亮的停色相不穩（#000 / #fff 的 h 是 0，那不是紅色）
    if (l < 12 || l > 92) continue
    if (!best || s > best[1]) best = [h, s]
  }
  if (!best || best[1] < 8) return null
  return best[0]
}

/* ══════════════════════════════════════════════════════════════════════
   組出整套變數
   ══════════════════════════════════════════════════════════════════════ */

/** 預設色相：Telegram-RMA 那套藏藍。沒有主題、或主題沒有色相時用它。 */
export const BASE_HUE = 221

/**
 * 依主題色相產生整套 CSS 變數。
 *
 * @param {number|null} hue 主題色相；null → 用 BASE_HUE
 * @param {boolean} isDark
 * @returns {Record<string,string>} 直接餵給 `style.setProperty` 的鍵值
 */
export function paletteFor(hue, isDark, bgOverride) {
  const k = isDark ? DARK : LIGHT
  const h = hue == null ? BASE_HUE : hue
  const out = {}

  /* 表面不必鉗制：它們本身就是「底」，對比是拿文字去比它們的。 */
  const rgb = {}
  for (const [name, s, l] of k.surfaces) {
    rgb[name] = hslToRgb(h, s, l)
    out[name] = hslToCss(h, s, l)
  }
  out[k.border[0]] = hslToCss(h, k.border[1], k.border[2])
  out[k.borderSoft[0]] = hslToCss(h, k.borderSoft[1], k.borderSoft[2])

  /*
   * 文字要對兩種底都讀得到：面板（bg-1）與卡片（bg-2）。
   * ⚠ **取兩者裡比較難的那個。** 只拿卡片去量的話，同一個顏色放到面板上就可能不夠
   *   ——而欄位標籤、時間戳兩邊都會出現。
   */
  const worstBg = contrast(rgb['--bg-1'], [255, 255, 255]) < contrast(rgb['--bg-2'], [255, 255, 255])
    ? rgb['--bg-1']
    : rgb['--bg-2']
  /*
   * ⚠ **卡片變成毛玻璃之後，文字的底就不是 `--bg-2` 了。** 底下的漸層會透上來，
   *   而那可能比卡片本身亮（深色主題）或暗（淺色主題）——所以呼叫端算得出合成後的
   *   實際顏色時要傳進來（`bgOverride`）。少了這一步，量到的對比是「理論上的」，
   *   而使用者看到的是另一回事。
   */
  const bgForText = bgOverride || (isDark
    ? (luminance(rgb['--bg-2']) > luminance(rgb['--bg-1']) ? rgb['--bg-2'] : rgb['--bg-1'])
    : (luminance(rgb['--bg-2']) < luminance(rgb['--bg-1']) ? rgb['--bg-2'] : rgb['--bg-1']))
  void worstBg

  for (const [name, s, l] of k.texts) {
    out[name] = hslToCss(h, s, fitL(h, s, l, bgForText, 4.5, isDark))
  }

  const [as, al] = k.accent
  out['--accent'] = hslToCss(h, as, al)
  out['--accent-2'] = hslToCss(h + k.accent2Shift, as, al)
  out['--accent-dim'] = hslToCss(h, k.accentDim[0], k.accentDim[1])
  out['--accent-soft'] = hslToCss(h, as, al, 15)
  out['--accent-text'] = hslToCss(
    h, k.accentText[0], fitL(h, k.accentText[0], k.accentText[1], bgForText, 4.5, isDark))

  /*
   * 主要按鈕上的字。
   *
   * ⚠ **不要為了讓白字讀得到而把主色壓暗。** 黃色系的主題要壓到 L≈35 才撐得住白字，
   *   那時候它已經不是黃色而是土色了——174 組主題會有一整片變成爛泥。改成**換字色**：
   *   白字不夠就用同色相的深墨色，主色本身一個字都不動。
   */
  const accentRgb = hslToRgb(h, as, al)
  out['--accent-on'] = contrast([255, 255, 255], accentRgb) >= 4.5
    ? '#ffffff'
    : hslToCss(h, 40, fitL(h, 40, 20, accentRgb, 4.5, false))

  /* 狀態色的色相固定，但明度一樣要鉗——紅色在深底上特別容易不夠。 */
  for (const [name, [s, l]] of Object.entries(k.status)) {
    const sh = STATUS_HUE[name]
    out[name] = hslToCss(sh, s, fitL(sh, s, l, bgForText, 4.5, isDark))
  }

  // 卡片頂部那道高光與陰影也要跟著深淺走，否則淺色主題會蓋上一層黑霧
  out['--card-hi'] = isDark
    ? 'linear-gradient(180deg, rgb(255 255 255 / 5%), transparent 42%)'
    : 'linear-gradient(180deg, rgb(255 255 255 / 80%), transparent 42%)'
  out['--shadow-card'] = isDark
    ? '0 1px 2px rgb(0 0 0 / 40%), 0 8px 24px rgb(0 0 0 / 26%)'
    : `0 1px 2px ${hslToCss(h, 30, 30, 8)}, 0 8px 24px ${hslToCss(h, 30, 30, 10)}`
  out['--shadow-pop'] = isDark
    ? '0 12px 40px rgb(0 0 0 / 55%)'
    : `0 12px 40px ${hslToCss(h, 30, 30, 20)}`
  out['--accent-grad'] = 'linear-gradient(135deg, var(--accent), var(--accent-2))'
  return out
}
