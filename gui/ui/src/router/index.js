import { createRouter, createWebHashHistory } from 'vue-router'
import Dashboard from '../views/Dashboard.vue'
import Logs from '../views/Logs.vue'

/**
 * ⚠ 用 hash history：頁面用 `file://` 載入。
 */
export default createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', name: 'dashboard', component: Dashboard },
    // 全螢幕的紀錄頁
    { path: '/logs', name: 'logs', component: Logs },
    { path: '/:pathMatch(.*)*', redirect: '/' }
  ]
})
