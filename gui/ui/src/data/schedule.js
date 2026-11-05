// 任務卡時間欄的文字與設定值互轉。純函式，`tools/check-schedule.mjs` 直接驗。

const CLOCK = /^(.*?)(\d{1,2}:\d{2})$/

/** 每週的時刻轉成顯示文字，連續的同一天只寫一次：週日 10:00、14:00、21:30。 */
export function formatWeekly(items) {
  let last = null
  return items
    .map((item) => {
      const [day, clock] = item.split(' ')
      const text = day === last ? clock : item
      last = day
      return text
    })
    .join('、')
}

/**
 * 任務卡要顯示的星期與時間欄文字。全部同一天時星期獨立出來（膠囊），欄位只放時刻；
 * 跨好幾天就回空的星期，星期留在欄位裡。
 */
export function splitWeekly(items) {
  const days = new Set(items.map((item) => item.split(' ')[0]))
  if (days.size !== 1) return { day: '', text: formatWeekly(items) }
  return { day: [...days][0], text: items.map((item) => item.split(' ')[1]).join(' ') }
}

/**
 * 時間欄的文字轉成要寫回設定檔的陣列。
 *
 * ⚠ 分隔符接受頓號、逗號與空白。
 * ⚠ 每週的時刻沒寫星期就沿用前一個，最前面的沿用 `defaultDay`。星期後面沒有時刻時原樣送出，
 *   由後端回報格式錯誤。
 */
export function parseTimes(text, weekly, defaultDay = '') {
  const parts = String(text)
    .split(/[、,，;；\s]+/)
    .map((s) => s.trim())
    .filter(Boolean)
  if (!weekly) return parts

  const out = []
  let day = defaultDay
  let pending = ''
  for (const part of parts) {
    const match = part.match(CLOCK)
    if (!match) {
      if (pending) out.push(pending)
      day = pending = part
      continue
    }
    if (match[1]) day = match[1]
    pending = ''
    out.push(day ? `${day} ${match[2]}` : match[2])
  }
  if (pending) out.push(pending)
  return out
}
