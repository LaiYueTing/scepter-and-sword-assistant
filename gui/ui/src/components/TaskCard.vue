<script setup>
import { computed } from 'vue'
import { NCheckbox, NInput, NInputNumber, NTooltip } from 'naive-ui'
import { Clock, Repeat } from 'lucide-vue-next'
import { useHostStore } from '../stores/host'

const props = defineProps({ task: { type: Object, required: true } })
const host = useHostStore()

/** 執行中不能改設定：引擎是**建立時**才套用開關的，中途改不會生效。 */
const locked = computed(() => host.running || host.closing)

const live = computed(() => host.taskStates[props.task.name] || null)

/**
 * 狀態徽章。
 *
 * ⚠ **顯示的是後端給的中文 `note`，不是 `state`。** 後者是狀態鍵
 *   （running / done / error），只拿來決定顏色——畫上去的話卡片會出現英文的
 *   「running」。這和 adb 的 `offline` 漏到下拉選單上是同一種毛病：狀態鍵是資料，
 *   不是訊息。
 */
const TONES = { running: 'ok', done: 'accent', error: 'bad' }

const badge = computed(() => {
  const s = live.value?.state
  if (s) return { text: live.value.note || s, tone: TONES[s] || 'ok', live: s === 'running' }
  if (!props.task.enabled) return { text: '已停用', tone: 'off', live: false }
  return { text: '待命', tone: 'idle', live: false }
})

/**
 * 下一輪什麼時候。
 *
 * ⚠ **用字要壓短，而且是量出來的。** 完整版「下一輪 08/20 08:00，4 小時 23 分後」
 *   在最小視窗下放不進卡片，會折成兩行——而說明換不換行決定卡片高度，五張卡就會
 *   各長各的。日期換成「今天／明天」、倒數只留最大的那個單位，完整版掛 tooltip。
 */
const nextText = computed(() => {
  const raw = props.task.next_run
  if (!raw) return '不排程'
  if (live.value?.note) return live.value.note

  const when = new Date(raw)
  const now = new Date()
  const day = dayWord(when, now)
  const clock = `${pad(when.getHours())}:${pad(when.getMinutes())}`
  const mins = Math.max(0, Math.round((when - now) / 60000))
  const left = mins >= 60 ? `${Math.floor(mins / 60)} 小時後` : `${mins} 分後`
  return `${day} ${clock} · ${left}`
})

const nextFull = computed(() => {
  const raw = props.task.next_run
  if (!raw) return '這份腳本沒有排定時刻'
  const when = new Date(raw)
  const mins = Math.max(0, Math.round((when - new Date()) / 60000))
  const h = Math.floor(mins / 60)
  return (
    `下一輪 ${when.getMonth() + 1}/${when.getDate()} ` +
    `${pad(when.getHours())}:${pad(when.getMinutes())}，` +
    (h ? `${h} 小時 ${mins % 60} 分後` : `${mins} 分後`)
  )
})

// 每週與每日是**兩個不同的鍵**。寫錯地方會讓腳本從「每週一」變成「每天」，
// 所以模式在後端就決定好，這裡只編它該編的那一個——要改種類就去改設定檔，
// 那才是明確的意思表示。
const timeKey = computed(() => (props.task.mode === 'weekly' ? 'weekly_at' : 'daily_at'))
const timeText = computed(() =>
  (props.task.mode === 'weekly' ? props.task.weekly_at : props.task.daily_at).join('、')
)

function pad(n) {
  return String(n).padStart(2, '0')
}
function dayWord(when, now) {
  const days = Math.floor((startOfDay(when) - startOfDay(now)) / 86400000)
  if (days === 0) return '今天'
  if (days === 1) return '明天'
  return `${when.getMonth() + 1}/${when.getDate()}`
}
function startOfDay(d) {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()
}

function edit(field, value) {
  // 路徑指到 tasks 底下那一筆的那個欄位（confedit 認得
  // `("tasks", "raid", "enabled")` 這種形狀），後端就地改寫那一行。
  host.save([{ path: ['tasks', props.task.name, field], value }]).catch(() => {})
}

/**
 * 時間欄要送**陣列**過去，不是那串顯示文字。
 *
 * ⚠ 分隔符全部收：使用者會打頓號、逗號或空白，而「打錯一個符號就整段變成一個
 *   時刻」是無聲的錯——設定檔會寫成 `daily_at: ["08:00、21:00"]`，載入時才炸。
 */
function editTimes(text) {
  const parts = String(text)
    .split(/[、,，;；\s]+/)
    .map((s) => s.trim())
    .filter(Boolean)
  edit(timeKey.value, parts)
}
</script>

<template>
  <div class="nc-card nc-hover p-3 flex flex-col gap-2" style="min-width: 0">
    <!--
      ⚠ 名稱與狀態徽章**拆成兩行**。擠在同一行時，最小視窗下卡片只剩 151px 可用，
        而勾選框要 114px、徽章要 61px——被切掉的正好是名稱最後一個字
        （使用者看過「自動每日活重」）。往下長不必跟任何人搶，寬度每多一份腳本
        就少一截。
    -->
    <label class="flex items-center gap-2 cursor-pointer" style="min-width: 0">
      <NCheckbox
        :checked="task.enabled"
        :disabled="locked"
        @update:checked="(v) => edit('enabled', v)"
      />
      <NTooltip trigger="hover">
        <template #trigger>
          <span class="truncate panel-title">{{ task.title }}</span>
        </template>
        {{ task.title }}（{{ task.name }}）
      </NTooltip>
    </label>

    <!--
      ⚠ **執行中的那顆點會呼吸，其餘的不會。** 五張卡同時在閃的話，「哪一個真的在
        跑」反而看不出來——而那正是這顆點存在的理由。
    -->
    <div>
      <span class="nc-pill" :class="`nc-pill--${badge.tone}`">
        <span class="nc-dot" :class="{ live: badge.live }" style="--glow: currentColor"></span>
        {{ badge.text }}
      </span>
    </div>

    <!-- 時間與次數也拆成兩行（grid 讓兩行的標籤對齊成一欄）。擠在同一行時
         時間欄只剩 56px 可畫字，而「08:00」要 35px——就是使用者看到的「)8:00」。 -->
    <div class="grid gap-1.5" style="grid-template-columns: auto 1fr; align-items: center">
      <span class="lab"><Clock :size="12" /> 時間</span>
      <NInput
        size="tiny"
        :value="timeText"
        :disabled="locked"
        :placeholder="task.mode === 'weekly' ? '週一 08:00' : '08:00、21:00'"
        @change="editTimes"
      />

      <span class="lab"><Repeat :size="12" /> 次數</span>
      <NTooltip trigger="hover" :disabled="!task.repeat_hint">
        <template #trigger>
          <NInputNumber
            size="tiny"
            :value="task.repeat"
            :min="0"
            :max="30"
            :disabled="locked"
            :show-button="false"
            placeholder="0 = 不限"
            @update:value="(v) => edit('repeat', v ?? 0)"
          />
        </template>
        {{ task.repeat_hint }}
      </NTooltip>
    </div>

    <!--
      ⚠ **一行到底 + 省略號，不要自動換行。** 執行中的狀態本來就時長時短
        （「BOSS 房戰鬥中　評級 A　5 分 02 秒」），換行會讓五張卡的高度各長各的、
        還會隨狀態跳動。資訊沒有少——完整版在 tooltip 裡。
    -->
    <NTooltip trigger="hover">
      <template #trigger>
        <div class="truncate" style="font-size: 12.5px; color: var(--text-1)">
          {{ nextText }}
        </div>
      </template>
      {{ live?.note || nextFull }}<br />排程：{{ task.schedule }}
    </NTooltip>
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
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12.5px;
  color: var(--text-1);
  white-space: nowrap;
}
</style>
