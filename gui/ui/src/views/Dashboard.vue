<script setup>
import { ref } from 'vue'
import { NAlert } from 'naive-ui'
import ControlBar from '../components/ControlBar.vue'
import DailyPanel from '../components/DailyPanel.vue'
import DevicePanel from '../components/DevicePanel.vue'
import LogView from '../components/LogView.vue'
import OptionsDialog from '../components/OptionsDialog.vue'
import TaskCard from '../components/TaskCard.vue'
import { useHostStore } from '../stores/host'

const host = useHostStore()
const showOptions = ref(false)
</script>

<template>
  <div class="flex flex-col gap-3 p-3.5 h-full" style="min-height: 0">
    <!-- 第一次執行：設定檔剛建立，提示先填裝置。 -->
    <NAlert v-if="host.isNew" type="warning" :bordered="false">
      這是第一次執行，已經建立 config.yaml。請先在下面填好模擬器的位址與連接埠。
    </NAlert>

    <!-- 任務卡，內部資訊往下排列。 -->
    <div
      class="grid gap-3"
      style="grid-template-columns: repeat(auto-fit, minmax(140px, 1fr))"
    >
      <TaskCard v-for="t in host.tasks" :key="t.name" :task="t" />
    </div>

    <ControlBar @open-options="showOptions = true" />

    <!-- ⚠ grid 項目也要 `min-height: 0`，否則撐不下時不會縮。 -->
    <div
      class="grid gap-3 flex-1"
      style="grid-template-columns: 320px 1fr; min-height: 0"
    >
      <!-- 左欄：模擬器在上（`flex: none`），當日計數在下（佔剩餘高度）。 -->
      <div class="flex flex-col gap-3" style="min-height: 0">
        <DevicePanel style="flex: none" />
        <DailyPanel style="flex: 1 1 auto; min-height: 0" />
      </div>
      <LogView style="min-height: 0" />
    </div>

    <OptionsDialog v-model:show="showOptions" />
  </div>
</template>
