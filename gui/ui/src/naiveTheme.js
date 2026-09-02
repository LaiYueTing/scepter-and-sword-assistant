import { nextTick, ref, watch } from 'vue'

/**
 * 把 CSS token 的**計算後實際值**餵給 naive-ui 的 theme-overrides。
 *
 * ⚠ **naive-ui 不吃 CSS 變數。** 寫 `primaryColor: 'var(--accent)'` 會讓它在
 *   `seemly` 解析顏色時丟例外：
 *
 *       Error: [seemly/rgba]: Invalid color value var(--accent).
 *
 *   它要拿真正的色碼去推導 hover / pressed / disabled 的色階，`var(...)` 那時還沒
 *   被瀏覽器解出來。而**這個例外的症狀極度誤導**：畫面不會整個壞掉，只有需要推導
 *   色階的那些元件（NInput、NCheckbox、NInputNumber）靜靜地 render 成空的
 *   `<!---->`，按鈕卻好好的——看起來像「輸入框忘了寫」而不是「有東西丟例外」。
 *   要不是把頁面的主控台輸出接出來看，這一條在畫面上完全查不出來（現在走
 *   `SSA_EVAL`：環境變數帶一段 JS 進去跑，結果印到 stderr）。
 *
 * ⚠ **不要在 JS 裡另外抄一份色票。** 那就變成同一組顏色有兩個來源，改了其中一份
 *   而漏掉另一份的那天不會有人發現。`getComputedStyle` 讀到的就是 tokens.css 裡
 *   那一份，換主題時重讀一次即可。
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
         * ⚠ **表面色也要交出去，不能只給主色。** naive-ui 自己的卡片／對話框／
         *   浮層底色是內建的固定灰，**不跟著背景主題走**——換一個主題只有我們
         *   自己畫的地方在變，naive 畫的那幾塊留在原地。使用者的回報是「介面
         *   設定視窗背景不會跟著改？」。
         *
         * ⚠ 一次在這裡交代完，不要每個對話框各補一條
         *   `.n-card { background: var(--bg-1) }`——那等於每加一個對話框就要
         *   記得補一次，而漏掉的那個只會在某些主題下才看得出來。
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
   * ⚠ 要等外觀真的套到 `<html>` 上、瀏覽器重算過樣式才讀得到新值，所以是 nextTick。
   * ⚠ **明暗和背景主題都要聽。** 只聽明暗的話，換背景主題時 naive 那幾塊會留在
   *   上一個色相上——所以傳進來的 key 是「明暗 + 主題 id」兩個合起來的字串。
   */
  watch(themeRef, async () => {
    await nextTick()
    read()
  })
  read()

  return overrides
}
