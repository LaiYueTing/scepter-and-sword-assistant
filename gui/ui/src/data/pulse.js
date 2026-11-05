/**
 * 燈號的呼吸：腳本執行中每秒換一個亮度，由 `surfaces.css` 依 `data-pulse` 畫出來。
 *
 * ⚠ 不要用 CSS 的無限動畫：box-shadow 動畫讓整個視窗每秒重畫 60 次，閒置約 100%（靜態 4%）。
 *   `steps()` 一樣每一格都在跑。
 * ⚠ 只在腳本執行時呼吸：每秒換一次亮度約 20%，排程等待的燈維持靜態。
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
