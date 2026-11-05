<script setup>
import { computed } from 'vue'
import { NCheckbox, NInput, NInputNumber, NTooltip } from 'naive-ui'
import { Clock, Repeat } from 'lucide-vue-next'
import { parseTimes, splitWeekly } from '../data/schedule'
import { useHostStore } from '../stores/host'

const props = defineProps({ task: { type: Object, required: true } })
const host = useHostStore()

/** 執行中不可改設定：引擎在建立時才套用開關。 */
const locked = computed(() => host.running || host.closing)

const live = computed(() => host.taskStates[props.task.name] || null)

/**
 * 狀態徽章。顯示後端給的中文 `note`；`state` 是狀態鍵，只決定顏色。
 */
const TONES = { running: 'ok', done: 'accent', error: 'bad' }

const badge = computed(() => {
  const s = live.value?.state
  if (s) return { text: live.value.note || s, tone: TONES[s] || 'ok', live: s === 'running' }
  if (!props.task.enabled) return { text: '已停用', tone: 'off', live: false }
  return { text: '待命', tone: 'idle', live: false }
})

/**
 * 下一輪的時間。日期寫「今天／明天」、倒數只留最大的單位，完整版放 tooltip。
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

// 每週與每日是兩個不同的鍵，模式由後端決定。
const timeKey = computed(() => (props.task.mode === 'weekly' ? 'weekly_at' : 'daily_at'))
const timeParts = computed(() =>
  props.task.mode === 'weekly'
    ? splitWeekly(props.task.weekly_at)
    : { day: '', text: props.task.daily_at.join(' ') }
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
  // 路徑指到 tasks 底下那一筆的欄位，後端就地改寫。
  host.save([{ path: ['tasks', props.task.name, field], value }]).catch(() => {})
}

/** 時間欄送陣列給後端。 */
function editTimes(text) {
  edit(timeKey.value, parseTimes(text, props.task.mode === 'weekly', timeParts.value.day))
}
</script>

<template>
  <div class="task-card nc-card nc-hover p-2.5 flex flex-col gap-2" style="min-width: 0">
    <!-- 名稱與狀態徽章分成兩行。 -->
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

    <!-- 只有執行中的那顆點會呼吸。 -->
    <div class="flex items-center gap-1.5">
      <span class="nc-pill" :class="`nc-pill--${badge.tone}`">
        <span class="nc-dot" :class="{ live: badge.live }" style="--glow: currentColor"></span>
        {{ badge.text }}
      </span>
      <span v-if="timeParts.day" class="nc-pill nc-pill--idle">{{ timeParts.day }}</span>
    </div>

    <!-- 時間與次數分成兩行，grid 讓標籤對齊成一欄。 -->
    <div class="grid gap-y-1.5 gap-x-1" style="grid-template-columns: auto 1fr; align-items: center">
      <span class="lab" title="時間"><Clock :size="12" /><span class="lab-text">時間</span></span>
      <!-- 會長高的多行欄，Enter 仍然是送出。 -->
      <NInput
        size="tiny"
        type="textarea"
        :autosize="{ minRows: 1, maxRows: 3 }"
        :resizable="false"
        :value="timeParts.text"
        :disabled="locked"
        :placeholder="task.mode === 'weekly' ? '週一 08:00' : '08:00 21:00'"
        @keydown.enter.prevent="$event.target.blur()"
        @change="editTimes"
      />

      <span class="lab" title="次數"><Repeat :size="12" /><span class="lab-text">次數</span></span>
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

    <!-- 單行加省略號，完整內容在 tooltip，卡片高度才不會跳動。 -->
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
 * 欄位標籤是功能性資訊，用 `--text-1`。
 */
.lab {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12.5px;
  color: var(--text-1);
  white-space: nowrap;
}

/* 卡片過窄時，欄位標籤只留圖示。 */
.task-card {
  container-type: inline-size;
}
@container (max-width: 170px) {
  .lab-text {
    display: none;
  }
  /* ⚠ 輸入區與量高度的 mirror 內距要相同。 */
  :deep(.n-input__textarea-el),
  :deep(.n-input__textarea-mirror),
  :deep(.n-input__placeholder) {
    padding-left: 4px;
    padding-right: 2px;
  }
}
</style>
