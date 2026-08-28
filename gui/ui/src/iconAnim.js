/**
 * 圖示的 hover 動畫，用事件委派掛在 document 上。
 *
 * 規則：平常靜止 → 滑鼠移上去才播 → 移開時**把當前這一輪跑完**才停。
 * 純 CSS 的 `:hover` 做不到最後那件事——移開的瞬間動畫會停在半途，圖示卡在奇怪的
 * 角度，比完全不動更礙眼。
 *
 * ⚠ **用委派而不是每個圖示各掛一組監聽。** 圖示會隨著任務卡與紀錄不斷重建，
 *   逐個掛的話要自己管拆除，漏一個就是一個永遠不會被回收的監聽器。
 *
 * ⚠ **只有互動元件才播。** 找到「直接包著 lucide svg 的那一層」之後還要確認它落在
 *   按鈕之類的東西裡——否則任務卡上「🕐 時間」那種純標籤也會在滑鼠掃過時轉起來，
 *   而這個視窗是拿來盯狀態的，畫面亂動就是雜訊。要讓非互動的圖示也動，就在它的
 *   任一層祖先加 `data-anim`。
 *
 * 實際播哪一種動作由 `styles/icons.css` 依 svg 的 `lucide-xxx` 類名決定，
 * 這裡只負責掛上／拿掉 `.ic-anim`。
 */

/** 沒有 `animationiteration` 可聽時的保險（動畫被 reduce-motion 關掉的情況）。 */
const STOP_FALLBACK_MS = 1600

/** 往上找幾層就放棄。lucide 的 svg 通常被按鈕包一到三層。 */
const MAX_DEPTH = 6

/** 「這是可以按的東西」——只有這些裡面的圖示會動。 */
const INTERACTIVE =
  'button, a, [role="button"], [data-anim], .n-button, .n-base-selection, .nc-btn, .nc-tab, .iconbtn, .swatch'

/**
 * 自己有 hover 動畫的元件掛 `data-no-anim`，這裡就完全不碰它。
 *
 * ⚠ **這不是可有可無的逃生門。** 主題那顆圖示靜止在 45°、hover 轉到 60°，而這套
 *   通用動畫是「播一輪回到原點就停」——兩個 transform 疊在同一顆 svg 上會互相覆蓋，
 *   結果是圖示在兩個角度之間亂跳，而且**看起來像 CSS 寫錯**，不會有人想到是兩套
 *   動畫在打架。
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
  host._icLeaving = true // 中途又移回來的話 start() 會把它清掉，這一輪就不停

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
   * ⚠ **要用 `pointerover` / `pointerout`，不能用 `pointerenter` / `pointerleave`。**
   *   後兩者不冒泡，委派收不到——掛在 document 上只會在滑鼠進出整個視窗時各觸發
   *   一次。這個坑很安靜：程式碼看起來完全正確，動畫就是不播。
   */
  document.addEventListener(
    'pointerover',
    (e) => {
      const host = hostOf(e.target)
      if (!host || !host.closest(INTERACTIVE)) return
      if (host.closest(OPT_OUT)) return
      if (host.contains(e.relatedTarget)) return // 在同一顆按鈕內部移動，不用重觸發
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
