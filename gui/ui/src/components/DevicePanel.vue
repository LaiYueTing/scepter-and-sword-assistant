<script setup>
import { computed, h, ref, watch } from 'vue'
import { NInput, NInputNumber, NSelect, NTooltip, useMessage } from 'naive-ui'
import { FileCog, Plug, Radar } from 'lucide-vue-next'
import ConfigEditor from './ConfigEditor.vue'
import { useHostStore } from '../stores/host'

const host = useHostStore()
const message = useMessage()

const showEditor = ref(false)
const serial = ref('')
const addr = ref('')
const port = ref(0)
const locked = computed(() => host.running || host.closing)

watch(
  () => host.device,
  (d) => {
    serial.value = d.serial || ''
    addr.value = d.host || ''
    port.value = d.port || 0
  },
  { immediate: true, deep: true }
)

/**
 * 探索到的裝置。旗標由後端排在字串最前面，收起來的下拉才看得到。
 */
/**
 * 清單裡每一項畫成多行。
 *
 * ⚠ `renderLabel` 是 prop，不是 slot：`NSelect` 沒有 slot，`<template #render-label>` 會被忽略。
 */
function renderChoice(option) {
  return h(
    'div',
    { style: 'white-space: pre-line; line-height: 1.5; padding: 2px 0' },
    option.detail
  )
}

const choices = computed(() =>
  host.found.map((f) => ({
    label: f.label,
    value: f.serial,
    disabled: !f.usable,
    detail: f.detail
  }))
)


async function discover() {
  try {
    await host.discover()
  } catch (e) {
    message.error(e.message)
  }
}

async function pick(value) {
  const found = host.found.find((f) => f.serial === value)
  if (!found) return
  // 探索會一次寫回 serial / host / port。跨機器連線時 serial 要留空，否則會蓋過 host:port。
  await save([
    { path: ['device', 'serial'], value: found.port ? '' : found.serial },
    { path: ['device', 'host'], value: found.host || host.device.host },
    { path: ['device', 'port'], value: found.port }
  ])
}

async function save(changes) {
  try {
    await host.save(changes)
    message.success('已寫回 config.yaml')
  } catch (e) {
    message.error(e.message)
  }
}

async function test() {
  try {
    await host.test()
  } catch (e) {
    message.error(e.message)
  }
}

watch(
  () => host.testResult,
  (r) => {
    if (!r) return
    if (r.ok) message.success(r.text)
    // 失敗訊息有七行，放進狀態列與紀錄面板。
    else message.error(r.text.split('\n')[0], { duration: 6000 })
  }
)
</script>

<template>
  <div class="card flex flex-col" style="min-height: 0">
    <div class="pane-hd">
      <Plug :size="15" style="color: var(--accent-text)" />
      <span class="hd-title">
        <span class="t">模擬器</span>
        <span class="s">{{ host.device.spec }}</span>
      </span>
      <div class="flex-1"></div>
      <button class="nc-btn nc-btn--sm" :disabled="locked || host.discovering" @click="discover">
        <Radar :size="13" :class="{ 'icon-spin running': host.discovering }" />
        探索
      </button>
    </div>

    <div class="flex flex-col gap-3 p-3" style="overflow: auto; min-height: 0">

    <NSelect
      v-if="choices.length"
      :options="choices"
      :value="null"
      placeholder="選一台套用到設定檔"
      size="small"
      :disabled="locked"
      :render-label="renderChoice"
      @update:value="pick"
    />

    <div class="grid gap-2" style="grid-template-columns: auto 1fr; align-items: center">
      <span class="lab">序號</span>
      <NTooltip trigger="hover">
        <template #trigger>
          <NInput
            v-model:value="serial"
            size="small"
            placeholder="auto 或留空（跨機器連線要留空）"
            :disabled="locked"
            @change="save([{ path: ['device', 'serial'], value: serial }])"
          />
        </template>
        <!-- `auto` 從已連上的裝置裡挑一台，本身不會 adb connect。 -->
        adb 的裝置序號。同一台電腦請填入 auto；跨機器連線請留空，改填下方的位址與連接埠
      </NTooltip>

      <span class="lab">位址</span>
      <NInput
        v-model:value="addr"
        size="small"
        placeholder="192.168.1.108"
        :disabled="locked"
        @change="save([{ path: ['device', 'host'], value: addr }])"
      />

      <span class="lab">連接埠</span>
      <NTooltip trigger="hover">
        <template #trigger>
          <NInputNumber
            v-model:value="port"
            size="small"
            :min="0"
            :max="65535"
            :show-button="false"
            :disabled="locked"
            @update:value="save([{ path: ['device', 'port'], value: port || 0 }])"
          />
        </template>
        <!--
          ⚠ 介面不指名任何一家模擬器，查不到埠號用「探索」。
          ⚠ 模擬器設定裡的 10.0.2.15 是虛擬機的 NAT 位址，要填實體機的 IP 加 ADB 埠。
        -->
        模擬器的 ADB 連接埠。在模擬器的設定中尋找 ADB 相關的資訊；如果不確定的話請點擊上方的「探索」
      </NTooltip>
    </div>

    <!--
      按鈕份量：測試連線用主色描邊（--soft），編輯設定檔用無邊框（--ghost）。
      ⚠ 實心的主要按鈕一個畫面只有一顆（開始執行）。
    -->
    <div class="flex items-center gap-2">
      <button
        class="nc-btn nc-btn--sm nc-btn--soft"
        :disabled="locked || host.testing"
        @click="test"
      >
        <Radar v-if="host.testing" :size="13" class="icon-spin running" />
        測試連線
      </button>
      <button
        class="nc-btn nc-btn--sm nc-btn--ghost"
        :disabled="locked"
        title="直接編輯 config.yaml 的原文（介面上沒有的欄位也改得到）"
        @click="showEditor = true"
      >
        <FileCog :size="14" /> 編輯設定檔
      </button>
    </div>

    <ConfigEditor v-model:show="showEditor" />
    </div>
  </div>
</template>

<style scoped>
/*
 * 欄位標籤是功能性資訊，用 `--text-1`。`--text-2` 只給時間戳、規格、補充說明。
 */
.lab {
  font-size: 12.5px;
  color: var(--text-1);
  white-space: nowrap;
}
</style>
