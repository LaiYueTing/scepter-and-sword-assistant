import { defineStore } from 'pinia'
import { api } from '../bridge'
import { applyAppearance } from '../data/gradients'

export const useUiStore = defineStore('ui', {
  state: () => ({
    theme: 'dark', // dark | light
    bgTheme: 'default', // 背景漸層主題的 id，見 data/gradients.js
    glow: 'breathe', // breathe | none：燈號動畫
    onClose: 'ask', // ask | tray | quit
    trayHint: true // 縮到系統匣時是否跳氣泡通知
  }),

  actions: {
    /**
     * 讀取偏好，存在 Python 那一側（`core/uistate.py` → ui.json）。
     */
    async load() {
      this.theme = (await this.pref('theme')) || 'dark'
      this.bgTheme = (await this.pref('bg_theme')) || 'default'
      this.glow = (await this.pref('glow')) || 'breathe'
      this.onClose = (await this.pref('on_close')) || 'ask'
      // ⚠ 布林值不可用 `|| 預設` 補：關閉時存的是 false。
      const hint = await this.pref('tray_hint')
      this.trayHint = hint === null ? true : !!hint
      this.apply()
    },

    async pref(key) {
      const res = await api.call('ui_get', { key })
      return res.ok ? res.result.value : null
    },

    /**
     * 把目前的外觀套到 `<html>` 上。
     *
     * ⚠ 配色由 `applyAppearance()` 用 inline 變數設定，`data-theme` 只影響少數 CSS 規則。
     *   兩者要一起更新，不可拆開呼叫。
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
    },

    async setTrayHint(value) {
      this.trayHint = value
      await api.call('ui_set', { key: 'tray_hint', value })
    }
  }
})
