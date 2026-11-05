/**
 * 燈號的呼吸：腳本執行中每秒換一個亮度，由 `surfaces.css` 依 `data-pulse` 畫出來。
 *
 * ⚠ 不要改回 CSS 的無限動畫。box-shadow 動畫讓整個視窗每秒重畫 60 次，卡片的
 *   backdrop-filter 也要跟著重算：只有一顆 8px 的燈在呼吸時，閒置就吃掉一整個核心
 *   （約 100%，靜態時 4%）。`steps()` 也沒有用，瀏覽器照樣每一格都在跑。
 *
 * ⚠ 只在腳本真的執行時才呼吸。排程等待一等就是幾小時，換一次亮度也要重畫整個視窗
 *   （每秒一次約 20%），等待中的燈維持靜態的發光。
 */
const SEQUENCE = ['0', '1', '2', '1']
const STEP_MS = 1000

let timer = null
let index = 0

function shouldPulse() {
  return (
    document.documentElement.dataset.glow !== 'none' &&
    !document.hidden &&
    !matchMedia('(prefers-reduced-motion: reduce)').matches &&
    document.querySelector('[data-task-running]') !== null
  )
}

export function startPulse() {
  if (timer !== null) return
  const root = document.documentElement
  timer = setInterval(() => {
    if (shouldPulse()) {
      index = (index + 1) % SEQUENCE.length
      root.dataset.pulse = SEQUENCE[index]
    } else if (root.dataset.pulse !== undefined) {
      delete root.dataset.pulse
    }
  }, STEP_MS)
}
