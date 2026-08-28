<script setup>
import { ref } from 'vue'
import { NAlert } from 'naive-ui'
import ControlBar from '../components/ControlBar.vue'
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
    <!-- 第一次執行：設定檔剛從範本建立，還沒填過裝置就直接連線只會得到一個
         看不懂的失敗。 -->
    <NAlert v-if="host.isNew" type="warning" :bordered="false">
      這是第一次執行，已經建立 config.yaml。請先在下面填好模擬器的位址與連接埠。
    </NAlert>

    <!--
      任務卡放最上面：「今天跑了沒、下一輪什麼時候」是打開視窗最先想知道的事，
      那以前只能去紀錄裡翻。
      ⚠ 卡片列橫跨整個視窗寬度，寬度**每多一份腳本就少一截**——所以卡片內部的
        資訊要往下長，不要往右擠。
    -->
    <div
      class="grid gap-3"
      style="grid-template-columns: repeat(auto-fit, minmax(200px, 1fr))"
    >
      <TaskCard v-for="t in host.tasks" :key="t.name" :task="t" />
    </div>

    <ControlBar @open-options="showOptions = true" />

    <!-- ⚠ **grid 項目也要 `min-height: 0`**，不能只設在 grid 上。項目預設是
         `min-height: auto`，撐不下時不會縮，於是整排把儀表板頂高、溢出到狀態列上。 -->
    <div
      class="grid gap-3 flex-1"
      style="grid-template-columns: 320px 1fr; min-height: 0"
    >
      <DevicePanel style="min-height: 0" />
      <LogView style="min-height: 0" />
    </div>

    <OptionsDialog v-model:show="showOptions" />
  </div>
</template>
