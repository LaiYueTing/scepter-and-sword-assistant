import { defineStore } from 'pinia'
import { useLogStore } from './logs'
import { api } from '../bridge'

/**
 * 後端的鏡像。**這裡不做任何判斷邏輯**——連線、規則引擎、排程全部在 Python 那一份，
 * 這個 store 只負責「拿到什麼、顯示什麼、按了什麼就轉發過去」。
 */
export const useHostStore = defineStore('host', {
  state: () => ({
    ready: false, // 後端起來了沒
    fatal: '', // 後端根本起不來（找不到 Python、被別的實例擋住）
    fatalTitle: '後端沒有在執行',
    version: '',
    configPath: '',
    logDir: '',
    isNew: false, // 這次執行才剛從範本建立設定檔
    frozen: false, // 後端是打包版還是原始碼
    device: { serial: '', host: '', port: 0, spec: '' },
    tasks: [],
    options: { items: {}, groups: [] },

    running: false,
    closing: false, // 正在收尾，按鈕全部要停用
    status: '待命中',
    // 任務卡各自的狀態：{ [name]: { state, note } }
    taskStates: {},

    discovering: false,
    found: [],
    testing: false,
    testResult: null, // { ok, text }

    update: null, // { found, version, error, can_apply, why, page }
    // 這次的查詢是使用者自己按的嗎。自動查那次不出聲（沒網路不是他當下關心的事），
    // 手動按的一定要回一句話——查完什麼都沒有的話，看起來就像那顆按鈕壞了。
    updateAsked: false,
    updateProgress: null // { done, total }
  }),

  getters: {
    /**
     * 有待裝的更新時「開始執行」是鎖住的。
     *
     * ⚠ 這比強制安裝好：它擋的是「用舊版無人看管地跑好幾小時」，而不是把使用者的
     *   程式換掉——壞掉的那一版仍然裝不進去。
     *
     * ⚠ 三種情況**不算**「非更新不可」，少判一種就會出事：
     *   查不到更新（那是我們這邊的問題，不該讓排程整晚不執行）、
     *   從原始碼執行（`can_apply` 本來就會拒絕換檔，鎖住等於讓開發動不了）、
     *   已經是最新。
     */
    updateRequired: (s) => Boolean(s.update?.found && s.update?.can_apply),

    canStart(s) {
      return s.ready && !s.running && !s.closing && !this.updateRequired
    },

    enabledTasks: (s) => s.tasks.filter((t) => t.enabled)
  },

  actions: {
    /** 接上事件，把第一份狀態拉下來。 */
    async init() {
      const logs = useLogStore()

      api.on((event, data) => {
        switch (event) {
          case 'ready':
            this.ready = true
            this.refresh()
            break
          case 'busy':
            // 已經有一個助手在執行中。這不是錯誤——後端好好地跑起來、發現鎖被
            // 別人握著、然後正常結束，所以標題不能寫「後端沒有在執行」。
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
            break
          case 'running':
            this.running = data
            if (!data) {
              this.status = '待命中'
              this.refresh() // 下一輪的排定時刻要重算
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
          case 'update':
            this.update = data
            break
          case 'update_progress':
            this.updateProgress = data
            break
          case 'update_done':
            this.updateProgress = null
            if (!data.ok) this.status = `更新失敗：${data.error}`
            break
          case 'fatal':
          case 'exit':
            this.ready = false
            // ⚠ **已經有說明就不要蓋掉。** `busy`（拿不到防多開的鎖）之後後端會
            //   正常結束，緊接著就來一則 exit——先寫的那句「助手已經在執行中」
            //   才是使用者要看的，而 exit 只知道「代碼 0」。照順序覆寫的話，
            //   唯一講得出原因的那句話會被最沒有資訊的那句取代。
            if (!this.closing && !this.fatal) {
              this.fatal =
                data.text || `後端結束了（代碼 ${data.code}）。詳細原因請看紀錄檔。`
            }
            break
        }
      })

      api.app.onClosing(() => {
        this.closing = true
        this.status = '停止中，正在執行收尾動作 ⋯'
      })

      // ⚠ **主動拉一次，不要只等 `ready` 事件。** 拉得到就代表後端活著，拉不到
      //   就安靜退回去等事件。少了這一步，事件漏接時的失敗樣子是**畫面看起來
      //   完全正常，只是永遠停在「正在啟動後端」**。
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
      // ⚠ 空的分組不要留——使用者的 config.yaml 沒有那份腳本的開關時，
      //   分頁點進去是一片空白，看起來像壞掉。
      this.options = { ...s.options, groups: s.options.groups.filter((g) => g.keys.length) }
      this.tasks = s.tasks
      this.running = s.running
      this.ready = true
    },

    async start(once = false, only = '') {
      await this.call('start', { once, only })
    },

    async stop() {
      await this.call('stop')
    },

    /**
     * 寫回 config.yaml。`changes` 是 `[{ path: ['options','claim_reward'], value }]`。
     *
     * ⚠ 路徑而不是整份物件：後端是**就地改寫**那一行，設定檔的註解才留得住。
     */
    async save(changes) {
      await this.call('save', { changes })
      await this.refresh()
    },

    /**
     * 探索可用的模擬器。
     *
     * ⚠ `auto` 是「開視窗時自動跑的那一次」。它**不做多埠掃描**——對同一台遠端
     *   主機連敲十幾個埠會被防毒判定成連接埠掃描而封鎖整台機器（實測被擋過
     *   5 小時），而開視窗是隨手就會做很多次的動作。
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
