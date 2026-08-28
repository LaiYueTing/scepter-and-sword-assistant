import { createRouter, createWebHashHistory } from 'vue-router'
import Dashboard from '../views/Dashboard.vue'
import Logs from '../views/Logs.vue'

/**
 * ⚠ **必須用 hash history。** 打包後頁面是用 `file://` 載入的，
 *   history 模式在重新整理或深層路徑上會直接 404——而那時已經沒有伺服器可以
 *   幫忙 rewrite 了。
 */
export default createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', name: 'dashboard', component: Dashboard },
    // 紀錄在儀表板上本來就看得到；這條是「只看紀錄」的全螢幕版，
    // 出問題要往回翻的時候一次看得多。
    { path: '/logs', name: 'logs', component: Logs },
    { path: '/:pathMatch(.*)*', redirect: '/' }
  ]
})
