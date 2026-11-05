import { defineStore } from 'pinia'

/** 面板保留的行數上限。 */
const CAP = 3000

/** 等級的顯示順序，固定不隨出現順序改變。 */
const LEVEL_ORDER = ['錯誤', '警告', '資訊', '等待']

let seq = 0

export const useLogStore = defineStore('logs', {
  state: () => ({
    lines: [],
    follow: true, // 自動捲到底
    filter: '', // 只看含這段文字的行
    // 選取的標籤，空陣列表示不過濾。
    levels: [],
    modules: []
  }),

  getters: {
    /**
     * 目前紀錄裡實際出現過的標籤與筆數。
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
        // 模組依名稱排序
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

    /** 是否正在過濾，決定是否顯示「清除篩選」。 */
    filtering: (s) => Boolean(s.filter.trim() || s.levels.length || s.modules.length),

    counts: (s) => ({
      warn: s.lines.filter((l) => l.level === '警告').length,
      error: s.lines.filter((l) => l.level === '錯誤').length
    })
  },

  actions: {
    /**
     * 接收一批紀錄。⚠ 整批一次改陣列：逐筆 push 每次都會觸發響應式更新。
     */
    append(batch) {
      const rows = batch.map((row) => ({
        id: ++seq,
        level: row.level,
        module: row.module,
        msg: row.msg,
        // 時間戳帶日期，不帶年份（面板只留 3000 行）。
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
