import { defineStore } from 'pinia'
import { useLogStore } from './logs'
import { useUiStore } from './ui'
import { api } from '../bridge'

/**
 * 後端的鏡像，不做判斷邏輯：接收狀態、顯示、轉發操作。
 */
export const useHostStore = defineStore('host', {
  state: () => ({
    ready: false, // 後端是否就緒
    fatal: '', // 後端無法啟動的原因
    fatalTitle: '後端沒有在執行',
    version: '',
    configPath: '',
    logDir: '',
    isNew: false, // 這次執行才剛從範本建立設定檔
    frozen: false, // 是否為打包版
    device: { serial: '', host: '', port: 0, spec: '' },
    tasks: [],
    options: { items: {}, groups: [] },
    // 當日計數（見 core/dailystate.py）。
    daily: { date: '', rows: [], path: '' },

    running: false,
    closing: false, // 結束程序執行中，按鈕全部停用
    // 「虛空裂縫」排隊中或執行中為 true，中斷鈕依此顯示
    riftPending: false,
    status: '待命中',
    // 任務卡各自的狀態：{ [name]: { state, note } }
    taskStates: {},

    discovering: false,
    found: [],
    testing: false,
    testResult: null, // { ok, text }

    update: null, // { found, version, error, can_apply, why, page }
    // 這次查詢是否由使用者按下。自動查詢不出聲，手動查詢一定要回報結果。
    updateAsked: false,
    updateProgress: null, // { done, total }
    // 換檔完成，等待使用者回答是否重新啟動。
    updateReady: null // { version }
  }),

  getters: {
    /**
     * 有待安裝的更新時「開始執行」是鎖住的。
     *
     * ⚠ 三種情況不鎖：查不到更新、從原始碼執行（`can_apply` 會拒絕換檔）、已經是最新。
     */
    updateRequired: (s) => Boolean(s.update?.found && s.update?.can_apply),

    canStart(s) {
      return s.ready && !s.running && !s.closing && !this.updateRequired
    },

    enabledTasks: (s) => s.tasks.filter((t) => t.enabled)
  },

  actions: {
    /** 接上事件，取得第一份狀態。 */
    async init() {
      const logs = useLogStore()

      api.on((event, data) => {
        switch (event) {
          case 'ready':
            this.ready = true
            this.refresh()
            break
          case 'busy':
            // 已經有一個助手在執行中，這不是錯誤。
            this.fatalTitle = '助手已經在執行中'
            this.fatal = data.text
            break
          case 'log':
            logs.append(data)
            break
          case 'status':
            this.status = data
            break
          case 'task':
            this.taskStates[data.name] = { state: data.state, note: data.note }
            if (data.name === 'rift' && data.state !== 'running') this.riftPending = false
            break
          case 'running':
            this.running = data
            if (!data) {
              this.riftPending = false
              this.status = '待命中'
              this.refresh() // 重算下一輪的排定時刻
            }
            break
          case 'failed':
            this.status = `執行失敗：${data}`
            break
          case 'discovered':
            this.discovering = false
            this.found = data.ok ? data.items : []
            if (!data.ok) this.status = `探索失敗：${data.error}`
            break
          case 'tested':
            this.testing = false
            this.testResult = data
            break
          case 'ui_pref':
            // 後端改了介面偏好（例如點擊系統匣通知），同步到開關上。
            if (data.key === 'tray_hint') useUiStore().trayHint = !!data.value
            break
          case 'update':
            this.update = data
            break
          case 'update_progress':
            this.updateProgress = data
            break
          case 'update_done':
            this.updateProgress = null
            if (data.ok) this.updateReady = { version: data.version }
            else this.status = `更新失敗：${data.error}`
            break
          case 'fatal':
          case 'exit':
            this.ready = false
            // ⚠ 已經有說明就不覆寫：`busy` 之後緊接著的 exit 只有結束碼。
            if (!this.closing && !this.fatal) {
              this.fatal =
                data.text || `後端已結束（結束碼 ${data.code}），詳細原因請看紀錄檔。`
            }
            break
        }
      })

      api.app.onClosing(() => {
        this.closing = true
        this.status = '停止中，正在執行結束程序 ⋯'
      })

      // ⚠ 主動取一次，不只等 `ready` 事件：取得到代表後端已就緒，取不到就繼續等事件。
      this.refresh().catch(() => {})
    },

    /** 呼叫後端。失敗會丟出帶中文訊息的 Error，由呼叫端決定怎麼顯示。 */
    async call(method, params) {
      const res = await api.call(method, params)
      if (!res.ok) throw new Error(res.error)
      return res.result
    },

    async refresh() {
      const s = await this.call('state')
      this.version = s.version
      this.configPath = s.config_path
      this.logDir = s.log_dir
      this.isNew = s.is_new
      this.frozen = s.frozen
      this.device = s.device
      // 空的分組不顯示。
      this.options = { ...s.options, groups: s.options.groups.filter((g) => g.keys.length) }
      this.tasks = s.tasks
      this.running = s.running
      this.ready = true
      this.loadDaily().catch(() => {})
    },

    /** 今天各項的計數。 */
    async loadDaily() {
      this.daily = await this.call('daily_state')
    },

    /** 把某一項（或全部，key 留空）今天的計數歸零。 */
    async resetDaily(key = '') {
      this.daily = await this.call('daily_reset', { key })
    },

    async start(once = false, only = '') {
      await this.call('start', { once, only })
    },

    async stop() {
      await this.call('stop')
    },

    /**
     * 現在就跑一輪不排程的腳本（虛空裂縫）。回傳 `now`：true 表示馬上開始。
     */
    async runNow(task) {
      const res = await this.call('run_now', { task })
      if (task === 'rift') this.riftPending = true
      return res
    },

    /** 中斷 runNow 加入的那一份，排程照常。回傳是否真的中斷到。 */
    async cancelRun(task) {
      const { cancelled } = await this.call('run_cancel', { task })
      if (task === 'rift') this.riftPending = false
      return cancelled
    },

    /**
     * 寫回 config.yaml。`changes` 是 `[{ path: ['options','claim_reward'], value }]`，後端就地改寫。
     */
    async save(changes) {
      await this.call('save', { changes })
      await this.refresh()
    },

    /**
     * 探索可用的模擬器。`auto` 表示開視窗時自動觸發，不做多埠掃描（見 core/discover.py）。
     */
    async discover(auto = false) {
      this.discovering = true
      this.found = []
      try {
        await this.call('discover', { auto })
      } catch (e) {
        this.discovering = false
        throw e
      }
    },

    async test() {
      this.testing = true
      this.testResult = null
      try {
        await this.call('test')
      } catch (e) {
        this.testing = false
        throw e
      }
    },

    async checkUpdate(quiet = false) {
      this.updateAsked = !quiet
      await this.call('update_check', { quiet })
    },

    async applyUpdate() {
      this.updateProgress = { done: 0, total: 0 }
      await this.call('update_apply')
    },

    reveal(what) {
      return this.call('reveal', { what })
    }
  }
})
