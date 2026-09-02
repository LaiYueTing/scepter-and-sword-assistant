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
 * 探索到的裝置。
 *
 * ⚠ **會被截斷的字串，重要的那段要排最前面。** 「［離線］」「［解析度不符］」
 *   由後端排在最前面——收起來的下拉只看得到開頭那段，「這台不能用」不能落在被切掉
 *   的那一截裡。
 */
/**
 * 清單裡每一項畫成多行。
 *
 * ⚠ **`renderLabel` 是 prop，不是 slot。** `NSelect` **一個 slot 都沒有用到**，
 *   所以 `<template #render-label>` 會被**安靜地忽略**——畫面退回單行的 `label`，
 *   再被 naive-ui 的 `text-overflow: ellipsis` 從尾巴切掉，變成
 *   「192.168.1.108:16480　SM-S938U　…」。而**解析度剛好就在被切掉的那一截**，
 *   那正是使用者要看的兩件事之一（另一個是埠號）。
 *
 * ⚠ 這個坑沒有任何錯誤訊息：寫錯的 slot 名稱只是不存在，Vue 不會抱怨。
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
  // 探索會一次寫回 serial / host / port 三個值。跨機器連線時 serial 要留空，
  // 否則它會蓋過 host:port。
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
    // 連線失敗那段有七行檢查清單，用 message 會被截掉——放進狀態列與紀錄面板，
    // 那邊有懸掛縮排排得下。
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
        <!-- `auto` 的語意是「從**已經連上**的裝置裡挑一台」，它自己不會 adb connect
             ——跨機器時 adb server 一重啟就什麼都不剩，而那只在半夜的排程炸出來。 -->
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
          ⚠ **不要在介面上指名哪一家模擬器。** 程式沒有綁定任何一家，只用標準的
            adb 指令；真正的條件只有兩個：開得了 ADB、調得到 720x1280 / 320dpi。
            寫上某個廠牌的選單路徑會讓用別家的人以為自己不能用。查不到埠號的
            出路是上面那顆「探索」，那對每一家都成立。
          ⚠ 模擬器系統設定裡的 10.0.2.15 是 Android 虛擬機的 NAT 位址，和連線
            無關。要填的是跑模擬器那台實體機的 IP 加上 ADB 埠。
        -->
        模擬器的 ADB 連接埠。在模擬器的設定中尋找 ADB 相關的資訊；如果不確定的話請點擊上方的「探索」
      </NTooltip>
    </div>

    <!--
      ⚠ **這一排的三顆按鈕份量要分得出來**，因為它們的性質差很多：
        「測試連線」是這個面板的目的（填完就是要驗一次），「探索」是
        找不到埠號時才用的輔助，「編輯設定檔」則是離開這個面板去做別的事。
        所以測試連線用主色描邊（`--soft`），編輯設定檔用無邊框（`--ghost`）。
      ⚠ 一個畫面只能有一顆實心的主要按鈕，那顆是「開始執行」。
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
 * ⚠ **欄位標籤用 `--text-1`，不要用 `--text-2`。** 「序號 / 位址 / 連接埠」
 *   「時間 / 次數」是**功能性**的——它們回答「這一格要填什麼」，讀者每次都要看。
 *   `--text-2` 是留給真正次要的東西的（時間戳、規格、補充說明）。
 *
 *   這一條不是對比值的問題（拉到 5.7:1 之後使用者仍然說「很多字都是灰色」），
 *   是**階層分錯了**：把太多東西丟進最弱的那一層，畫面看起來就整片發灰。
 */
.lab {
  font-size: 12.5px;
  color: var(--text-1);
  white-space: nowrap;
}
</style>
