<script setup>
import { computed, ref } from 'vue'
import { NTooltip, useMessage } from 'naive-ui'
import { CircleX, FolderOpen, Play, Settings2, SkipForward, Sparkles, Square } from 'lucide-vue-next'
import { useHostStore } from '../stores/host'

const emit = defineEmits(['open-options'])
const host = useHostStore()
const message = useMessage()
const starting = ref(false)
const riftStarting = ref(false)

/**
 * 待更新時只鎖會操作遊戲的兩顆，測試連線與玩法設定照常。
 */
const startDisabled = computed(() => !host.canStart || starting.value)

/**
 * 停用的原因。格式：先寫現在的狀態，再寫結果。
 */
const whyDisabled = computed(() => {
  if (host.closing) return '結束程序執行中：正在逐層退回家園，結束前不能開始新的一輪'
  if (host.running) return '執行中：已經有一輪在跑了'
  if (host.updateRequired) return `有待安裝的更新：要先更新到 v${host.update.version} 才能開始執行`
  if (!host.ready) return '後端尚未就緒：還在啟動，稍候再試'
  return ''
})

async function run(once) {
  starting.value = true
  try {
    await host.start(once)
  } catch (e) {
    message.error(e.message)
  } finally {
    starting.value = false
  }
}

/**
 * 虛空裂縫由這顆按鈕手動觸發。排程等待中會立刻執行，正在跑別的腳本時接在後面；
 * 結束程序執行中與待更新時鎖住。
 */
const riftDisabled = computed(
  () => !host.ready || host.closing || host.updateRequired || riftStarting.value
)

const riftHint = computed(() => {
  if (host.closing) return '結束程序執行中：結束前不能開始新的一輪'
  if (host.updateRequired) return `有待安裝的更新：要先更新到 v${host.update.version} 才能開始執行`
  if (!host.ready) return '後端尚未就緒：還在啟動，稍候再試'
  return '執行虛空裂縫剩下的場次，完成後自動離開地圖。請先自己組好隊伍、停在活動地圖上再按。排程等待中也可以按，跑完會回去等下一個時刻'
})

/** 裂縫排隊中或執行中才顯示中斷鈕。 */
const riftActive = computed(
  () => host.riftPending || host.taskStates.rift?.state === 'running'
)

async function cancelRift() {
  try {
    const cancelled = await host.cancelRun('rift')
    message.info(cancelled ? '已中斷虛空裂縫，排程照常' : '虛空裂縫沒有在跑')
  } catch (e) {
    message.error(e.message)
  }
}

async function rift() {
  riftStarting.value = true
  try {
    const { now } = await host.runNow('rift')
    message.info(now ? '開始打虛空裂縫' : '正在跑別的腳本，虛空裂縫排在它之後')
  } catch (e) {
    message.error(e.message)
  } finally {
    riftStarting.value = false
  }
}

async function stop() {
  try {
    await host.stop()
    // 停止到真正結束要 14～18 秒（結束程序逐層退回家園），要先顯示訊息。
    message.info('已要求停止，正在執行結束程序（約 15 秒）⋯')
  } catch (e) {
    message.error(e.message)
  }
}
</script>

<template>
  <div class="flex flex-wrap items-center gap-2">
    <NTooltip trigger="hover" :disabled="!whyDisabled">
      <template #trigger>
        <button class="nc-btn nc-btn--primary" :disabled="startDisabled" @click="run(false)">
          <Play :size="15" /> 開始執行
        </button>
      </template>
      <!-- ⚠ 停用的按鈕要寫出原因。 -->
      {{ whyDisabled }}
    </NTooltip>

    <NTooltip trigger="hover">
      <template #trigger>
        <button class="nc-btn" :disabled="startDisabled" @click="run(true)">
          <SkipForward :size="15" /> 只跑一輪
        </button>
      </template>
      {{ whyDisabled || '依排程跑一輪就結束，不留在背景等下一個時刻' }}
    </NTooltip>

    <button class="nc-btn" :disabled="!host.running || host.closing" @click="stop">
      <Square :size="14" /> 停止
    </button>

    <NTooltip trigger="hover">
      <template #trigger>
        <button class="nc-btn" :disabled="riftDisabled || riftActive" @click="rift">
          <Sparkles :size="15" /> 虛空裂縫
        </button>
      </template>
      {{ riftActive ? '虛空裂縫正在排隊或執行中' : riftHint }}
    </NTooltip>

    <NTooltip v-if="riftActive" trigger="hover">
      <template #trigger>
        <button class="nc-btn" :disabled="host.closing" @click="cancelRift">
          <CircleX :size="15" /> 中斷裂縫
        </button>
      </template>
      只中斷虛空裂縫這一份，排程照常。正在跑的立刻結束、不做結束程序，人會留在當時的畫面
    </NTooltip>

    <div class="flex-1"></div>

    <NTooltip trigger="hover">
      <template #trigger>
        <button
          class="nc-btn"
          :disabled="host.running || host.closing"
          @click="emit('open-options')"
        >
          <Settings2 :size="15" /> 玩法設定
        </button>
      </template>
      <!-- 引擎在建立時才套用開關，執行中不可修改。 -->
      {{
        host.running
          ? '執行中不能改設定：引擎在建立時才套用開關，改了不會生效'
          : '每份腳本一個分頁。改完要按「儲存」才會寫回 config.yaml'
      }}
    </NTooltip>

    <button class="nc-btn nc-btn--ghost" @click="host.reveal('logs')">
      <FolderOpen :size="15" /> 日誌資料夾
    </button>
  </div>
</template>
