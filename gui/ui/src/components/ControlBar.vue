<script setup>
import { computed, ref } from 'vue'
import { NTooltip, useMessage } from 'naive-ui'
import { FolderOpen, Play, Settings2, SkipForward, Square } from 'lucide-vue-next'
import { useHostStore } from '../stores/host'

const emit = defineEmits(['open-options'])
const host = useHostStore()
const message = useMessage()
const starting = ref(false)

/**
 * ⚠ **只鎖「會操作遊戲」的那兩顆。** 測試連線與玩法設定照常——那兩個正是排查
 *   「為什麼連不上」時要用的，一起鎖住只會妨礙人。
 */
const startDisabled = computed(() => !host.canStart || starting.value)

/**
 * 為什麼不能按。
 *
 * ⚠ **每一則都要先講「現在是什麼狀態」，再講「所以怎樣」。** 停用的按鈕若說不出
 *   原因，看起來就是壞了——而使用者不會知道要去按標題列那顆更新。
 */
const whyDisabled = computed(() => {
  if (host.closing) return '收尾中：正在逐層退回家園，結束前不能開始新的一輪'
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

async function stop() {
  try {
    await host.stop()
    // 按下停止到真正結束實測 14～18 秒（收尾要逐層退回家園）。這句話一定要說，
    // 否則看起來像當掉。
    message.info('已要求停止，正在執行收尾動作（約 15 秒）⋯')
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
      <!-- ⚠ 停用的按鈕一定要講得出原因，否則它看起來就是壞了——而使用者不會知道
           要去按標題列那顆更新。 -->
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
      <!-- 引擎是**建立時**才套用開關的，中途改不會生效。讓使用者以為改了有用，
           比不給改更糟。 -->
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
