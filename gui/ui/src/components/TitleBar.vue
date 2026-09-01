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
const showAsk = ref(false)      // 查到新版：要不要現在裝
const showUpdated = ref(false)  // 裝好了：要不要現在重新啟動
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
 * 「連得上嗎」。
 *
 * ⚠ **後端沒有持續維護一個連線旗標**，所以這裡只認兩種**確定**的證據：測試連線成功、
 *   或探索到一台位址相符而且規格也對的裝置。**沒有證據時燈是暗的，不是亮的**——
 *   把「還不知道」畫成綠燈，等於在說謊，而使用者正是靠這顆燈決定要不要按開始執行。
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
 * 現在正在跑哪一份腳本。沒有的話這顆 chip 整個不出現。
 *
 * ⚠ **只認 `running`。** 用「有 state 就算」的話，前一份腳本跑完留下的 `done`
 *   會先被挑中，標題列就停在已經結束的那一份上。
 *
 * ⚠ **顯示 `note`（中文）而不是 `state`（狀態鍵）**，否則畫面上會出現「running」。
 */
const runningTask = computed(() => {
  if (!host.running) return null
  const hit = host.tasks.find((t) => host.taskStates[t.name]?.state === 'running')
  return hit ? { title: hit.title, note: host.taskStates[hit.name].note } : null
})

/**
 * 檢查更新的結果。三種結果分開講：
 *
 *   error  → 檢查更新失敗：{原因}
 *   found  → 偵測到新版本 vX.Y.Z
 *   其餘   → 已經是最新版本（vX.Y.Z）
 *
 * ⚠ **「已經是最新」和「查不到」在後端都是「沒有新版可裝」**，但沒網路時說
 *   「已經是最新版本」就是在說謊，而使用者正是靠那句話決定要不要繼續用舊版
 *   跑整晚。後端因此多回一個 `error`（空字串＝真的問到了 GitHub）。
 *
 * ⚠ 旗標放在 store 而不是這裡：「關於」那個對話框裡也有一顆檢查更新，
 *   兩個入口要說同一句話。自動查的那次走 quiet，不設旗標，所以不出聲。
 */
watch(
  () => host.update,
  (u) => {
    if (!u) return
    // 查到而且裝得下去就當場問。⚠ **自動查到那次也要問**：看不到那顆按鈕的人
    //   （縮在系統匣、視窗一掛好幾天）否則會一直用著舊版。執行中不問，那時
    //   本來就不給更新。
    const ask = u.found && u.can_apply && !host.running && !host.closing
    if (ask) showAsk.value = true

    if (!host.updateAsked) return
    host.updateAsked = false
    if (u.error) message.warning(`檢查更新失敗：${u.error}`)
    // ⚠ 跳了框就不要再跳 toast——同一件事講兩次。
    else if (u.found) {
      if (!ask) message.success(`偵測到新版本 v${u.version}`)
    } else message.success(`已經是最新版本（v${host.version}）`)
  }
)

/**
 * 換好檔之後問使用者要不要現在重新啟動。
 *
 * ⚠ **一定要問，而且問完才排重啟。** 換檔本身只是把新的 EXE 放到位，畫面上
 *   完全沒有反應——使用者的回報就是「他不會 UI 跳出來詢問是否重啟嗎?」。
 *   而排定重啟的背景工作是「等這個行程結束就啟動新版」，先排後問的話它會
 *   一直潛伏著，等使用者哪天關掉程式就自己跳出來。
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

    <!--
      狀態燈號。**這是打開視窗最先想知道的兩件事**：連得上嗎、現在在跑什麼。
      以前這兩個答案都只能去紀錄裡翻。
    -->
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
      <!--
        ⚠ **兩種狀態都要說「現在是什麼」，不是只說「你該做什麼」。** 亮著的時候
          要講清楚驗過了哪兩件事（連得上、規格對），因為那正是這顆燈的全部含義；
          暗著的時候要講清楚它是「還沒驗」而不是「驗過了，壞的」——兩者差很多。
      -->
      {{
        deviceLive
          ? `連線正常：ADB 連線成功，畫面規格 ${host.device.spec || '720x1280 / 320dpi'}`
          : '尚未驗證：ADB 連線狀態未知。請點擊「測試連線」或「探索」'
      }}
    </NTooltip>

    <div
      v-if="runningTask"
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

    <!-- 這個程式自己的按鈕，一組。 -->
    <div class="no-drag flex items-center gap-1">
      <!-- 下載一百多 MB 一定要有進度條。只有一行狀態文字在變的話，
           一兩分鐘裡視窗看起來就像當住了。 -->
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
        <!-- ⚠ 停用的按鈕一定要講得出原因。少了這句，那顆按鈕看起來就是壞了。 -->
        {{
          host.running
            ? '執行中不更新：換檔要重新啟動，會中斷正在打的副本或討伐'
            : host.update?.found
              ? `${updateLabel}（${host.update.size_text}，裝完會問你要不要重新啟動）`
              : '檢查更新'
        }}
      </NTooltip>

      <!--
        ⚠ **明暗切換放在這裡，不放進介面設定的對話框。** 這是每天會按好幾次的
          東西，藏進一個要先打開的對話框裡等於降級。
      -->
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
        介面設定：背景主題、狀態燈號、按下 ✕ 時的行為
      </NTooltip>

      <!--
        ⚠ **「關於」要看得到，不能只藏在選單裡。** 版本、設定檔與日誌的實際路徑
          是回報問題時第一個要抄的東西，而它們原本只寫在狀態列的一角。
      -->
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
      這個「視窗」的按鈕，另一組。
      ⚠ **中間那條分隔線是必要的，不是裝飾。** 左邊那組操作的是程式（查更新、換主題），
        右邊這組操作的是視窗——兩件完全不同的事，排成一排卻會被讀成同一組。

      ⚠ **視窗鍵刻意維持方角、滿高、貼到最右邊。** 那是 Windows 的慣例，而且有實際
        理由：最大化時「關閉」落在螢幕角落，游標甩過去一定會停住（Fitts 定律，
        角落等於無限大的目標）。加了圓角或內距就會把這個性質毀掉。
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
/* 版本號給一塊底色，才不會被讀成標題的一部分 */
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
 * 主題圖示靜止在 45°，hover 再轉到 60°。
 * ⚠ **這顆刻意不走 `iconAnim.js` 的那套 hover 動畫。** 那套是「播一輪就停」，
 *   而這裡要的是「停在另一個角度」——兩種動畫疊在同一顆圖示上會互相打架。
 */
.theme-i {
  color: var(--accent-text);
  transform: rotate(45deg);
  transition: transform 0.35s ease, color 0.2s ease;
}
.theme-i.light {
  color: var(--amber);
}
/*
 * ⚠ **幅度要看得出來。** 原本是 45° → 60°，只差 15 度——旁邊那顆下載圖示是
 *   上下彈 3px 的循環動畫，兩者放在一起時使用者的回報是「右邊那兩顆沒有效果」。
 *   轉到 -15° 是 60 度的差距，一眼就分得出來，而且仍然是**停在另一個角度**
 *   （不是循環動畫），所以不會和 `iconAnim.js` 那套打架。
 */
.iconbtn:hover .theme-i {
  transform: rotate(-15deg) scale(1.08);
}
</style>
