/**
 * 從背景主題推導整套配色：面板、卡片、框線、輸入框、文字都跟著主題的色相。
 *
 * HSL 上只換 H（色相），S 與 L 走固定的階梯，對比由 `tools/check-contrast.mjs`
 * 掃過全部 174 組主題驗證。
 *
 * ⚠ 不要改 LADDER 的 L 值，要讓主題更鮮豔請調 S。
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
 * ⚠ 一定要輸出 hex 或 `rgba(r, g, b, a)`：naive-ui 的 seemly 解不了空白分隔的 `hsl()`，
 *   需要推導色階的元件（NCheckbox、NInput 等）會 render 成空的。`tools/check-tokens.mjs` 會檢查。
 */
function hslToCss(h, s, l, alpha) {
  const [r, g, b] = hslToRgb(h, s, l)
  if (alpha === undefined) {
    return '#' + [r, g, b].map((v) => v.toString(16).padStart(2, '0')).join('')
  }
  return `rgba(${r}, ${g}, ${b}, ${(alpha / 100).toFixed(3)})`
}

/** 相對亮度（WCAG）。 */
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
 * 找出最接近原本 L、又能達到目標對比的明度（二分）。
 *
 * ⚠ 不可省略：相對亮度不是只看 L，同樣 L=55% 的黃色比藍色亮得多。
 * ⚠ 目標要加裕度：`hslToCss` 把 L 四捨五入到小數一位，剛好 4.50 輸出後會低於門檻。
 *
 * @param {number} h 色相
 * @param {number} s 飽和度
 * @param {number} l0 想要的明度（過得了就原樣回傳）
 * @param {number[]} bg 這個顏色的底色
 * @param {number} target 目標對比
 * @param {boolean} lighten true 表示往亮的方向找（深色主題的文字）
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
 * 深色階梯的 L 值：8.4 / 12.4 / 16.1 / 21.2，框線 23.9。
 * ⚠ `bg2`（卡片）比 `bg1`（面板）亮：卡片浮在面板上面。
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
  // 主色：H 跟著主題，S/L 限制在範圍內
  accent: [70, 62],
  accent2Shift: 28, // 第二個主色的色相偏移（度）
  accentText: [78, 74], // 卡片上的小字用，比按鈕底色亮
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
 * ⚠ 狀態色的色相固定，不跟著主題：綠＝好、黃＝注意、紅＝壞。
 */
const STATUS_HUE = { '--green': 152, '--amber': 42, '--red': 2, '--neon': 168 }

/* ══════════════════════════════════════════════════════════════════════
   從漸層萃取色相
   ══════════════════════════════════════════════════════════════════════ */

/** 取出漸層字串裡的所有色停。 */
export function stopsOf(css) {
  return (css.match(/#[0-9a-f]{3,8}\b/gi) || []).map(hexToRgb)
}

/** 漸層上最亮與最暗的色停。 */
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

/** 兩個顏色照 alpha 混合。`t` 是前者的比例。 */
export function mixRgb(a, b, t) {
  return a.map((v, i) => v * t + b[i] * (1 - t))
}

/**
 * 取漸層的色相：最飽和的那一停（平均會讓互補色抵消）。
 *
 * ⚠ 沒有色相的漸層（`wg40`）回傳 null，由呼叫端用預設色相。
 */
export function hueOf(css) {
  const stops = stopsOf(css)
  if (!stops.length) return null
  let best = null
  for (const rgb of stops) {
    const [h, s, l] = rgbToHsl(rgb)
    // 太暗或太亮的色停色相不穩定
    if (l < 12 || l > 92) continue
    if (!best || s > best[1]) best = [h, s]
  }
  if (!best || best[1] < 8) return null
  return best[0]
}

/* ══════════════════════════════════════════════════════════════════════
   組出整套變數
   ══════════════════════════════════════════════════════════════════════ */

/** 預設色相（藏藍），沒有主題或主題沒有色相時使用。 */
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

  /* 表面不需要限制，對比是拿文字去比。 */
  const rgb = {}
  for (const [name, s, l] of k.surfaces) {
    rgb[name] = hslToRgb(h, s, l)
    out[name] = hslToCss(h, s, l)
  }
  out[k.border[0]] = hslToCss(h, k.border[1], k.border[2])
  out[k.borderSoft[0]] = hslToCss(h, k.borderSoft[1], k.borderSoft[2])

  /*
   * ⚠ 文字要對面板（bg-1）與卡片（bg-2）都讀得到，取兩者裡比較難的。
   */
  const worstBg = contrast(rgb['--bg-1'], [255, 255, 255]) < contrast(rgb['--bg-2'], [255, 255, 255])
    ? rgb['--bg-1']
    : rgb['--bg-2']
  /*
   * ⚠ 卡片是毛玻璃，文字的底是合成後的顏色，呼叫端用 `bgOverride` 傳入。
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
   * 主要按鈕上的字。⚠ 白字不夠時換成同色相的深墨色，不把主色壓暗。
   */
  const accentRgb = hslToRgb(h, as, al)
  out['--accent-on'] = contrast([255, 255, 255], accentRgb) >= 4.5
    ? '#ffffff'
    : hslToCss(h, 40, fitL(h, 40, 20, accentRgb, 4.5, false))

  /* 狀態色的色相固定，明度要限制。 */
  for (const [name, [s, l]] of Object.entries(k.status)) {
    const sh = STATUS_HUE[name]
    out[name] = hslToCss(sh, s, fitL(sh, s, l, bgForText, 4.5, isDark))
  }

  // 卡片頂部的高光與陰影跟著深淺走
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
