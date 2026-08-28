<script setup>
import { computed, onMounted, ref } from 'vue'
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

// 讓 naive-ui 跟著我們的 token 走，而不是各畫各的。
// ⚠ 只覆寫「會跟主題變」的那幾個，整份抄一遍的話 naive-ui 之後改了預設值我們也
//   跟不上，而漏掉的那一個會變成上一套配色的殘留。細節與那個很難查的例外見
//   `naiveTheme.js`。
// ⚠ **key 要把背景主題也算進去。** 只看明暗的話，換一個背景主題時 naive 畫的
//   對話框與浮層會留在上一個色相上——那正是「介面設定視窗背景不會跟著改」。
const overrides = useNaiveTokens(computed(() => `${ui.theme}/${ui.bgTheme}`))

onMounted(async () => {
  await ui.load()
  await host.init()
  api.app.onConfirmClose(() => (showClose.value = true))

  // 開視窗時自動探索一次，讓「連得上嗎」那顆燈一開窗就有答案。
  // ⚠ 走 auto：只敲設定檔指名的那一個埠，不做多埠掃描（見 host.discover）。
  setTimeout(() => host.discover(true).catch(() => {}), 400)

  // 查一次更新，延後讓畫面先畫出來。
  // ⚠ 走 quiet：查不到就完全不出聲，沒網路不是使用者當下關心的事。
  setTimeout(() => host.checkUpdate(true).catch(() => {}), 1500)
})
</script>

<template>
  <NConfigProvider :theme="theme" :theme-overrides="overrides" :locale="zhTW" :date-locale="dateZhTW">
    <NMessageProvider :max="3" placement="bottom">
      <NDialogProvider>
        <div class="flex flex-col h-full">
          <TitleBar />

          <!-- ⚠ `overflow: hidden` 不是裝飾。少了它，內容比 main 高的時候會**畫到
                 狀態列上面**（flex 只決定位置，不會裁切溢出）——狀態列還在原位，
                 只是被壓在下面看不見。 -->
          <main class="app-canvas flex-1" style="min-height: 0; overflow: hidden">
            <!-- 後端起不來時，蓋掉整個內容區並說明原因。留著一個看起來正常
                 但按什麼都沒反應的介面，比一句話糟得多。 -->
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
