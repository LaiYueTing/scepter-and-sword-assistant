/**
 * 圖示的 hover 動畫，用事件委派掛在 document 上：移上去才播，移開時跑完當前這一輪才停。
 * 實際的動作由 `styles/icons.css` 依 svg 的 `lucide-xxx` 類名決定，這裡只掛上或移除 `.ic-anim`。
 *
 * ⚠ 只有互動元件才播，要讓非互動的圖示也動，就在祖先加 `data-anim`。
 */

/** 收不到 `animationiteration` 時的保險（reduce-motion）。 */
const STOP_FALLBACK_MS = 1600

/** 往上找的層數上限。 */
const MAX_DEPTH = 6

/** 互動元件的選擇器。 */
const INTERACTIVE =
  'button, a, [role="button"], [data-anim], .n-button, .n-base-selection, .nc-btn, .nc-tab, .iconbtn, .swatch'

/**
 * 自己有 hover 動畫的元件掛 `data-no-anim`，這裡不處理。
 *
 * ⚠ 兩個 transform 疊在同一顆 svg 上會互相覆蓋（主題圖示）。
 */
const OPT_OUT = '[data-no-anim]'

/** 從事件目標往上找「直接子層就是 lucide svg」的那一層。 */
function hostOf(node) {
  let el = node instanceof Element ? node : null
  for (let depth = 0; el && depth < MAX_DEPTH; depth++, el = el.parentElement) {
    if (el.querySelector?.(':scope > svg.lucide')) return el
  }
  return null
}

function start(host) {
  host._icLeaving = false
  host.classList.add('ic-anim')
}

function stopWhenCycleEnds(host) {
  if (!host.classList.contains('ic-anim')) return
  host._icLeaving = true // 中途移回來時由 start() 清除

  const svg = host.querySelector(':scope > svg.lucide')
  if (!svg) {
    host.classList.remove('ic-anim')
    return
  }
  const done = () => {
    if (host._icLeaving) host.classList.remove('ic-anim')
  }
  svg.addEventListener('animationiteration', done, { once: true })
  setTimeout(done, STOP_FALLBACK_MS)
}

export function mountIconAnim() {
  /*
   * ⚠ 要用 `pointerover` / `pointerout`：`pointerenter` / `pointerleave` 不冒泡，委派收不到。
   */
  document.addEventListener(
    'pointerover',
    (e) => {
      const host = hostOf(e.target)
      if (!host || !host.closest(INTERACTIVE)) return
      if (host.closest(OPT_OUT)) return
      if (host.contains(e.relatedTarget)) return // 在同一顆按鈕內部移動
      start(host)
    },
    { passive: true }
  )

  document.addEventListener(
    'pointerout',
    (e) => {
      const host = hostOf(e.target)
      if (!host) return
      if (host.contains(e.relatedTarget)) return // 還在同一顆按鈕裡
      stopWhenCycleEnds(host)
    },
    { passive: true }
  )
}
