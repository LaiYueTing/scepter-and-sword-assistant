<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import {
  NConfigProvider,
  NDialogProvider,
  NMessageProvider,
  NSpin,
  darkTheme,
  dateZhTW,
  zhTW
} from 'naive-ui'
import TitleBar from './components/TitleBar.vue'
import StatusBar from './components/StatusBar.vue'
import CloseDialog from './components/CloseDialog.vue'
import { useHostStore } from './stores/host'
import { useUiStore } from './stores/ui'
import { useNaiveTokens } from './naiveTheme'
import { api } from './bridge'

const host = useHostStore()
const ui = useUiStore()
const showClose = ref(false)

const theme = computed(() => (ui.theme === 'dark' ? darkTheme : null))

// 把 token 交給 naive-ui，只覆寫會跟主題變的項目，細節見 `naiveTheme.js`。
// ⚠ key 要包含背景主題，否則換主題時對話框與浮層會留在上一個色相。
const overrides = useNaiveTokens(computed(() => `${ui.theme}/${ui.bgTheme}`))

// 第一份狀態畫好後通知外殼顯示主視窗。兩次 rAF：第二次執行時，前一幀已經繪製。
watch(
  () => host.version || host.fatal,
  (shown) => {
    if (shown) requestAnimationFrame(() => requestAnimationFrame(() => api.call('ui_painted')))
  }
)

onMounted(async () => {
  await ui.load()
  await host.init()
  api.app.onConfirmClose(() => (showClose.value = true))

  // 開視窗時自動探索一次。⚠ 走 auto：只敲設定檔指名的埠，不做多埠掃描。
  setTimeout(() => host.discover(true).catch(() => {}), 400)

  // 延後查一次更新。⚠ 走 quiet：查不到不出聲。
  setTimeout(() => host.checkUpdate(true).catch(() => {}), 1500)
})
</script>

<template>
  <NConfigProvider :theme="theme" :theme-overrides="overrides" :locale="zhTW" :date-locale="dateZhTW">
    <NMessageProvider :max="3" placement="bottom">
      <NDialogProvider>
        <div class="flex flex-col h-full">
          <TitleBar />

          <!-- ⚠ `overflow: hidden`：flex 不裁切溢出，內容會畫到狀態列上面。 -->
          <main class="app-canvas flex-1" style="min-height: 0; overflow: hidden">
            <!-- 後端無法啟動時蓋掉內容區並說明原因。 -->
            <div v-if="host.fatal" class="h-full grid place-items-center p-8">
              <div class="card p-6" style="max-width: 560px">
                <h2 class="font-semibold mb-2" :style="{ color: 'var(--red)' }">
                  {{ host.fatalTitle }}
                </h2>
                <p style="white-space: pre-wrap; line-height: 1.7; color: var(--text-1)">
                  {{ host.fatal }}
                </p>
              </div>
            </div>

            <div v-else-if="!host.ready" class="h-full grid place-items-center">
              <NSpin size="large">
                <template #description>正在啟動後端 ⋯</template>
              </NSpin>
            </div>

            <RouterView v-else />
          </main>

          <StatusBar />
          <CloseDialog v-model:show="showClose" />
        </div>
      </NDialogProvider>
    </NMessageProvider>
  </NConfigProvider>
</template>
