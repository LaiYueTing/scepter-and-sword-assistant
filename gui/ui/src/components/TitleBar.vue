<script setup>
import { computed, ref, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { NProgress, NTooltip, useMessage } from 'naive-ui'
import {
  ArrowDownToLine,
  Info,
  LayoutDashboard,
  Moon,
  Palette,
  ScrollText,
  Sun,
  Swords
} from 'lucide-vue-next'
import AboutDialog from './AboutDialog.vue'
import UpdateAskDialog from './UpdateAskDialog.vue'
import UpdateDialog from './UpdateDialog.vue'
import AppearanceDialog from './AppearanceDialog.vue'
import WindowControls from './WindowControls.vue'
import { useHostStore } from '../stores/host'
import { useUiStore } from '../stores/ui'

const host = useHostStore()
const ui = useUiStore()
const router = useRouter()
const route = useRoute()
const message = useMessage()
const showAppearance = ref(false)
const showAbout = ref(false)
const showAsk = ref(false)      // 查到新版的詢問框
const showUpdated = ref(false)  // 更新完成的詢問框
const installedVersion = ref('')

const percent = computed(() => {
  const p = host.updateProgress
  if (!p || !p.total) return 0
  return Math.min(100, Math.round((p.done / p.total) * 100))
})

const updateLabel = computed(() =>
  host.update?.found ? `更新到 v${host.update.version}` : '檢查更新'
)

/* ---------- 狀態燈號 ---------- */

/** 目標裝置：跨機器是 IP:埠，同一台是 adb 序號。 */
const target = computed(() => {
  const d = host.device
  if (d.host && d.port) return `${d.host}:${d.port}`
  return d.serial || '尚未設定'
})

/**
 * 連線燈號。只認測試連線成功，或探索到位址相符且規格正確的裝置；沒有證據時不亮。
 */
const deviceLive = computed(() => {
  if (host.testResult?.ok) return true
  return host.found.some(
    (f) => f.usable && f.ok_size && (f.serial === target.value || f.serial === host.device.serial)
  )
})

const deviceSub = computed(() => {
  if (host.device.spec) return host.device.spec
  return deviceLive.value ? '已連線' : '尚未測試'
})

/**
 * 正在跑的腳本，沒有就不顯示。⚠ 只認 `running`，顯示 `note`。
 */
const runningTask = computed(() => {
  if (!host.running) return null
  const hit = host.tasks.find((t) => host.taskStates[t.name]?.state === 'running')
  return hit ? { title: hit.title, note: host.taskStates[hit.name].note } : null
})

/**
 * 檢查更新的結果：
 *
 *   error  → 檢查更新失敗：{原因}
 *   found  → 偵測到新版本 vX.Y.Z
 *   其餘   → 已經是最新版本（vX.Y.Z）
 *
 * 手動查詢的旗標放在 store，「關於」對話框共用；自動查詢不設旗標，不出聲。
 */
watch(
  () => host.update,
  (u) => {
    if (!u) return
    // 查到而且可以安裝就詢問（自動查詢也一樣），執行中不問。
    const ask = u.found && u.can_apply && !host.running && !host.closing
    if (ask) showAsk.value = true

    if (!host.updateAsked) return
    host.updateAsked = false
    if (u.error) message.warning(`檢查更新失敗：${u.error}`)
    // 跳了詢問框就不跳 toast。
    else if (u.found) {
      if (!ask) message.success(`偵測到新版本 v${u.version}`)
    } else message.success(`已經是最新版本（v${host.version}）`)
  }
)

/**
 * 換檔完成後詢問是否重新啟動。⚠ 問完才排定重新啟動。
 */
watch(
  () => host.updateReady,
  (v) => {
    if (!v) return
    installedVersion.value = v.version
    showUpdated.value = true
    host.updateReady = null
  }
)

async function onUpdate() {
  try {
    if (!host.update?.found) {
      await host.checkUpdate(false)
      message.info('正在檢查更新 ⋯')
      return
    }
    if (!host.update.can_apply) {
      message.warning(host.update.why || '這個環境沒辦法自動更新')
      return
    }
    await host.applyUpdate()
  } catch (e) {
    message.error(e.message)
  }
}
</script>

<template>
  <header class="app-chrome drag flex items-center gap-2.5 border-b" style="height: 48px; padding: 0 4px 0 12px">
    <div class="brand">
      <span class="logo"><Swords :size="14" color="#fff" /></span>
      <span class="nm">杖劍傳說助手</span>
      <span v-if="host.version" class="ver">v{{ host.version }}</span>
    </div>

    <!-- 分頁切換：儀表板 / 紀錄 -->
    <nav class="no-drag flex items-center gap-1">
      <button class="nc-tab" :class="{ on: route.name === 'dashboard' }" @click="router.push('/')">
        <LayoutDashboard :size="14" /> 儀表板
      </button>
      <button class="nc-tab" :class="{ on: route.name === 'logs' }" @click="router.push('/logs')">
        <ScrollText :size="14" /> 日誌
      </button>
    </nav>

    <div class="flex-1"></div>

    <!-- 狀態燈號：連線狀態與正在跑的腳本。 -->
    <NTooltip trigger="hover">
      <template #trigger>
        <div class="chip no-drag" :class="{ live: deviceLive }" style="--glow: var(--neon)">
          <span class="nc-dot" :class="{ live: deviceLive }" style="--glow: var(--neon)"></span>
          <div class="tx">
            <div class="mn">{{ target }}</div>
            <div class="sb">{{ deviceSub }}</div>
          </div>
        </div>
      </template>
      <!-- 亮時寫驗過哪兩件事（連得上、規格對），暗時寫「尚未驗證」。 -->
      {{
        deviceLive
          ? `連線正常：ADB 連線成功，畫面規格 ${host.device.spec || '720x1280 / 320dpi'}`
          : '尚未驗證：ADB 連線狀態未知。請點擊「測試連線」或「探索」'
      }}
    </NTooltip>

    <div
      v-if="runningTask"
      data-task-running
      class="chip no-drag live"
      style="--glow: var(--green)"
      :title="`${runningTask.title}：${runningTask.note}`"
    >
      <span class="nc-dot live" style="--glow: var(--green)"></span>
      <div class="tx">
        <div class="mn">{{ runningTask.title }}</div>
        <div class="sb">{{ runningTask.note }}</div>
      </div>
    </div>

    <!-- 程式的按鈕。 -->
    <div class="no-drag flex items-center gap-1">
      <!-- 下載進度條。 -->
      <div v-if="host.updateProgress" class="flex items-center gap-2" style="width: 170px">
        <NProgress
          type="line"
          :percentage="percent"
          :height="6"
          :show-indicator="false"
          color="var(--accent)"
          rail-color="var(--bg-3)"
        />
        <span style="color: var(--text-2); font-size: 12px">{{ percent }}%</span>
      </div>

      <NTooltip v-else trigger="hover">
        <template #trigger>
          <button
            class="iconbtn"
            :class="{ on: host.update?.found }"
            :disabled="host.running || host.closing"
            @click="onUpdate"
          >
            <ArrowDownToLine :size="17" />
          </button>
        </template>
        <!-- ⚠ 停用的按鈕要寫出原因。 -->
        {{
          host.running
            ? '執行中不更新：換檔要重新啟動，會中斷正在打的副本或討伐'
            : host.update?.found
              ? `${updateLabel}（${host.update.size_text}，裝完會問你要不要重新啟動）`
              : '檢查更新'
        }}
      </NTooltip>

      <!-- 明暗切換。 -->
      <NTooltip trigger="hover">
        <template #trigger>
          <button
            class="iconbtn"
            data-no-anim
            @click="ui.setTheme(ui.theme === 'dark' ? 'light' : 'dark')"
          >
            <component
              :is="ui.theme === 'dark' ? Moon : Sun"
              class="theme-i"
              :class="{ light: ui.theme !== 'dark' }"
              :size="17"
            />
          </button>
        </template>
        {{ ui.theme === 'dark' ? '目前為深色，切換到淺色' : '目前為淺色，切換到深色' }}
      </NTooltip>

      <NTooltip trigger="hover">
        <template #trigger>
          <button
            class="iconbtn"
            :class="{ on: ui.bgTheme !== 'default' }"
            @click="showAppearance = true"
          >
            <Palette :size="17" />
          </button>
        </template>
        介面設定：背景主題、狀態燈號、關閉與縮小時的行為
      </NTooltip>

      <!-- 關於：版本與路徑。 -->
      <NTooltip trigger="hover">
        <template #trigger>
          <button class="iconbtn" @click="showAbout = true">
            <Info :size="17" />
          </button>
        </template>
        關於：版本、更新狀態、設定檔與日誌的位置
      </NTooltip>
    </div>

    <!--
      視窗的按鈕，與程式的按鈕用分隔線分開。
      ⚠ 視窗鍵維持方角、滿高、貼到最右邊：最大化時「關閉」在螢幕角落（Fitts 定律）。
    -->
    <div class="no-drag flex items-stretch self-stretch">
      <span class="sep"></span>
      <WindowControls />
    </div>

    <AppearanceDialog v-model:show="showAppearance" />
    <AboutDialog v-model:show="showAbout" />
    <UpdateAskDialog v-model:show="showAsk" />
    <UpdateDialog v-model:show="showUpdated" :version="installedVersion" />
  </header>
</template>

<style scoped>
.brand {
  display: flex;
  align-items: center;
  gap: 8px;
  padding-right: 4px;
  flex: none;
}
.logo {
  width: 26px;
  height: 26px;
  border-radius: 7px;
  background: var(--accent-grad);
  display: grid;
  place-items: center;
  flex: none;
}
.brand .nm {
  font-weight: 600;
  letter-spacing: 0.02em;
  white-space: nowrap;
}
/* 版本號的底色 */
.brand .ver {
  font-size: 11px;
  color: var(--text-2);
  background: var(--bg-3);
  padding: 1px 6px;
  border-radius: 6px;
  white-space: nowrap;
}

.sep {
  align-self: center;
  width: 1px;
  height: 18px;
  margin: 0 6px 0 4px;
  background: var(--border);
}

/*
 * 主題圖示靜止在 45°，hover 轉到另一個角度。⚠ 掛 data-no-anim，不走 `iconAnim.js`。
 */
.theme-i {
  color: var(--accent-text);
  transform: rotate(45deg);
  transition: transform 0.35s ease, color 0.2s ease;
}
.theme-i.light {
  color: var(--amber);
}
.iconbtn:hover .theme-i {
  transform: rotate(-15deg) scale(1.08);
}
</style>
