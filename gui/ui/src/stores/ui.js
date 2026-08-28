import { defineStore } from 'pinia'
import { api } from '../bridge'
import { applyAppearance } from '../data/gradients'

export const useUiStore = defineStore('ui', {
  state: () => ({
    theme: 'dark', // dark | light
    bgTheme: 'default', // 背景漸層主題的 id，見 data/gradients.js
    glow: 'breathe', // breathe | none —— 燈號要不要呼吸
    onClose: 'ask' // ask | tray | quit
  }),

  actions: {
    /**
     * ⚠ **偏好存在 Python 那一側（`core/uistate.py` → 專案旁邊的 ui.json）。**
     *   兩份介面共用同一份——各存各的話，換一張臉主題就跳回預設，而使用者不會
     *   知道為什麼。
     */
    async load() {
      this.theme = (await this.pref('theme')) || 'dark'
      this.bgTheme = (await this.pref('bg_theme')) || 'default'
      this.glow = (await this.pref('glow')) || 'breathe'
      this.onClose = (await this.pref('on_close')) || 'ask'
      this.apply()
    },

    async pref(key) {
      const res = await api.call('ui_get', { key })
      return res.ok ? res.result.value : null
    },

    /**
     * 把目前的外觀套到 `<html>` 上。
     *
     * ⚠ **顏色不是靠 `data-theme` 換的。** 那個屬性只給少數幾條 CSS 規則看（卡片
     *   高光的方向、毛玻璃）。真正的整套配色是 `applyAppearance()` 用 inline 變數
     *   蓋在 `<html>` 上的——面板、卡片、框線、輸入框、次要文字全部跟著背景主題的
     *   色相走，而不是只換背景。
     *
     * ⚠ **兩件事一定要一起做。** 明度階梯在深淺兩套是相反的，只改 `data-theme` 而
     *   不重算 palette 會得到「淺色的底配深色的字」；只重算 palette 而不改
     *   `data-theme`，卡片高光會留在上一套。所以寫在同一個函式裡，不要拆開呼叫。
     *
     * 這也是為什麼紀錄面板的一般訊息不內嵌顏色：內嵌的話，切換之後早先寫進去的
     * 幾百行會留在舊主題上。
     */
    apply() {
      document.documentElement.dataset.theme = this.theme
      document.documentElement.dataset.glow = this.glow
      applyAppearance(this.bgTheme, this.theme === 'dark')
    },

    async setTheme(value) {
      this.theme = value
      this.apply()
      await api.call('ui_set', { key: 'theme', value })
    },

    async setBgTheme(value) {
      this.bgTheme = value
      this.apply()
      await api.call('ui_set', { key: 'bg_theme', value })
    },

    async setGlow(value) {
      this.glow = value
      this.apply()
      await api.call('ui_set', { key: 'glow', value })
    },

    async setOnClose(value) {
      this.onClose = value
      await api.call('ui_set', { key: 'on_close', value })
    }
  }
})
