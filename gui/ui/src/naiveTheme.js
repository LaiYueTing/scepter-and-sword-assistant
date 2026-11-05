import { nextTick, ref, watch } from 'vue'

/**
 * 把 CSS token 的計算後實際值交給 naive-ui 的 theme-overrides。
 *
 * ⚠ naive-ui 不接受 CSS 變數：`var(--accent)` 會在 seemly 解析時丟例外，
 *   需要推導色階的元件（NInput、NCheckbox、NInputNumber）會 render 成空的。
 */
export function useNaiveTokens(themeRef) {
  const overrides = ref({})

  function read() {
    const cs = getComputedStyle(document.documentElement)
    const pick = (name) => cs.getPropertyValue(name).trim()
    overrides.value = {
      common: {
        primaryColor: pick('--accent'),
        primaryColorHover: pick('--accent-2'),
        primaryColorPressed: pick('--accent-dim'),
        primaryColorSuppl: pick('--accent-2'),
        successColor: pick('--green'),
        warningColor: pick('--amber'),
        errorColor: pick('--red'),

        /*
         * ⚠ 表面色也要設定，naive-ui 的卡片、對話框、浮層底色不跟著主題。
         */
        baseColor: pick('--bg-0'),
        bodyColor: pick('--bg-0'),
        cardColor: pick('--bg-1'),
        modalColor: pick('--bg-1'),
        popoverColor: pick('--bg-2'),
        tableColor: pick('--bg-1'),
        borderColor: pick('--border'),
        dividerColor: pick('--border-soft'),

        borderRadius: pick('--radius-input'),
        fontFamily:
          "'Microsoft JhengHei UI', 'Microsoft JhengHei', 'Segoe UI', system-ui, sans-serif"
      }
    }
  }

  /*
   * ⚠ 用 nextTick：外觀套用、樣式重算之後才讀得到新值。
   * ⚠ key 同時包含明暗與主題 id。
   */
  watch(themeRef, async () => {
    await nextTick()
    read()
  })
  read()

  return overrides
}
