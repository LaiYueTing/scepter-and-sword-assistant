import { defineStore } from 'pinia'

/** 面板最多留這麼多行。掛整夜的話紀錄會很長，而真正要看的永遠是最近那一段。 */
const CAP = 3000

/**
 * 等級的顯示順序。⚠ **不要用出現順序排**——那會讓標籤列在執行中跳來跳去
 * （冒出第一個警告的瞬間整排就重排了），而使用者正想按其中一個。
 */
const LEVEL_ORDER = ['錯誤', '警告', '資訊', '等待']

let seq = 0

export const useLogStore = defineStore('logs', {
  state: () => ({
    lines: [],
    follow: true, // 自動捲到底
    filter: '', // 只看含這段文字的行
    // 選起來的標籤。**空陣列 = 不過濾**，不是「全部排除」——這個區別很重要，
    // 否則一開始沒選任何標籤時畫面會是空的。
    levels: [],
    modules: []
  }),

  getters: {
    /**
     * 目前紀錄裡實際出現過的標籤與筆數。
     *
     * ⚠ **只列出現過的。** 固定列出所有等級與模組的話，畫面上會有一排永遠是 0
     *   的標籤——而這個介面的重點是「今天實際發生了什麼」。
     */
    tags: (s) => {
      const levels = new Map()
      const modules = new Map()
      for (const l of s.lines) {
        levels.set(l.level, (levels.get(l.level) || 0) + 1)
        modules.set(l.module, (modules.get(l.module) || 0) + 1)
      }
      const rank = (name) => {
        const i = LEVEL_ORDER.indexOf(name)
        return i < 0 ? LEVEL_ORDER.length : i
      }
      return {
        levels: [...levels]
          .map(([name, count]) => ({ name, count }))
          .sort((a, b) => rank(a.name) - rank(b.name)),
        // 模組沒有天然的輕重之分，照名稱排就好——至少是穩定的
        modules: [...modules]
          .map(([name, count]) => ({ name, count }))
          .sort((a, b) => a.name.localeCompare(b.name, 'zh-Hant'))
      }
    },

    visible: (s) => {
      const needle = s.filter.trim().toLowerCase()
      if (!needle && !s.levels.length && !s.modules.length) return s.lines
      return s.lines.filter((l) => {
        if (s.levels.length && !s.levels.includes(l.level)) return false
        if (s.modules.length && !s.modules.includes(l.module)) return false
        if (!needle) return true
        return (
          l.msg.toLowerCase().includes(needle) ||
          l.module.toLowerCase().includes(needle)
        )
      })
    },

    /** 有沒有在過濾。用來決定要不要顯示「清掉篩選」。 */
    filtering: (s) => Boolean(s.filter.trim() || s.levels.length || s.modules.length),

    counts: (s) => ({
      warn: s.lines.filter((l) => l.level === '警告').length,
      error: s.lines.filter((l) => l.level === '錯誤').length
    })
  },

  actions: {
    /**
     * 收一批紀錄。
     *
     * ⚠ **整批一次改陣列**，不要 for 迴圈逐筆 push：每 push 一次就觸發一次
     *   響應式更新，副本開場那種一秒好幾行的時候會把整個畫面拖住。後端已經
     *   把紀錄批次送過來了（`Channel._pump`），這裡不要把它拆散。
     */
    append(batch) {
      const rows = batch.map((row) => ({
        id: ++seq,
        level: row.level,
        module: row.module,
        msg: row.msg,
        // 時間戳要帶日期。這個視窗常常掛整夜，隔天早上看到一行「03:12:07」
        // 根本分不出是哪天。不寫年份是因為面板只留 3000 行、不可能跨年。
        time: formatTime(row.ts)
      }))
      const next = this.lines.concat(rows)
      this.lines = next.length > CAP ? next.slice(next.length - CAP) : next
    },

    toggle(kind, name) {
      const list = this[kind]
      const i = list.indexOf(name)
      this[kind] = i < 0 ? [...list, name] : list.filter((x) => x !== name)
    },

    clearTags() {
      this.levels = []
      this.modules = []
      this.filter = ''
    },

    clear() {
      this.lines = []
      this.clearTags()
    }
  }
})

function formatTime(ts) {
  const d = new Date(ts * 1000)
  const p = (n) => String(n).padStart(2, '0')
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(
    d.getMinutes()
  )}:${p(d.getSeconds())}`
}
