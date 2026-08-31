<script setup>
import { computed, onMounted, watch } from 'vue'
import { NPopconfirm, NTooltip, useMessage } from 'naive-ui'
import { CalendarCheck, RotateCcw } from 'lucide-vue-next'
import { useHostStore } from '../stores/host'

const host = useHostStore()
const message = useMessage()

// 執行中不給重設。引擎是在**建立時**把計數讀進規則裡的，中途歸零要下一輪才生效
// ——按了看起來沒作用是最難查的那種形狀。和「執行中把設定面板鎖住」同一個理由。
const locked = computed(() => host.running || host.closing)
const rows = computed(() => host.daily.rows)
const anything = computed(() => rows.value.some((r) => r.done > 0))

function tone(r) {
  if (!r.limit) return 'nc-pill--off'
  return r.done >= r.limit ? 'nc-pill--ok' : 'nc-pill--idle'
}

async function reset(key) {
  try {
    await host.resetDaily(key)
    message.success(key ? '已重設這一項' : '已重設全部計數')
  } catch (e) {
    message.error(e.message)
  }
}

onMounted(() => host.loadDaily().catch(() => {}))

// 計數是在腳本跑的時候變的，所以每次有腳本開始或結束就重讀一次。
watch(() => host.taskStates, () => host.loadDaily().catch(() => {}), { deep: true })
</script>

<template>
  <div class="card flex flex-col" style="min-height: 0">
    <div class="pane-hd">
      <CalendarCheck :size="15" style="color: var(--accent-text)" />
      <span class="hd-title">
        <span class="t">當日計數</span>
        <span class="s">換日自動歸零</span>
      </span>
      <div class="flex-1"></div>
      <NPopconfirm v-if="anything" @positive-click="reset('')">
        <template #trigger>
          <button class="nc-btn nc-btn--sm nc-btn--ghost" :disabled="locked">
            <RotateCcw :size="13" /> 全部重設
          </button>
        </template>
        重設之後這些項目今天會重新計算，可能再花掉一次資源。
      </NPopconfirm>
    </div>

    <!-- ⚠ 直向內距比別的面板小一級（`py-2`）：這一塊和上面的模擬器面板共用一欄，
           而**多出來的高度應該留給模擬器**（它有下拉、三個欄位和三顆按鈕）。實測
           用 `p-3` 時兩塊加起來比欄高多 4px，於是兩邊各自冒出一條 2px 的捲軸。 -->
    <div class="flex flex-col gap-2 px-3 py-2" style="overflow: auto; min-height: 0">
      <!--
        ⚠ **這裡不是「今天跑過哪些腳本」。** 列出來的是**答案不在畫面上**的那幾件事
          （打過幾場競技場、捐了幾次晨星、買了幾次領獎次數）。次數用盡、獎勵已領
          這些腳本進遊戲看得出來，本來就不需要記。
      -->
      <p v-if="!rows.length" class="empty">今天還沒有任何計數。</p>

      <div v-for="r in rows" :key="r.key" class="dc-row">
        <div style="min-width: 0">
          <div class="what">{{ r.label }}</div>
          <div class="who">{{ r.task }}</div>
        </div>

        <NTooltip trigger="hover">
          <template #trigger>
            <span class="nc-pill" :class="tone(r)">
              <span>{{ r.done }}{{ r.limit ? ` / ${r.limit}` : '' }}</span>
            </span>
          </template>
          {{ r.limit ? `今天已經做了 ${r.done} 次，上限 ${r.limit} 次` : `今天已經做了 ${r.done} 次` }}
        </NTooltip>

        <NPopconfirm @positive-click="reset(r.key)">
          <template #trigger>
            <button class="iconbtn" :disabled="locked || !r.done" title="把這一項今天的計數歸零">
              <RotateCcw :size="14" />
            </button>
          </template>
          重設之後這一項今天會重新計算，可能再花掉一次資源。
        </NPopconfirm>
      </div>
    </div>
  </div>
</template>

<style scoped>
.dc-row {
  display: grid;
  grid-template-columns: 1fr auto auto;
  align-items: center;
  gap: 8px;
}

/*
 * ⚠ 做的是什麼用 `--text-1`，腳本名才用 `--text-2`。前者是這一列在講的事，
 *   讀者每次都要看；後者只是「它屬於誰」。把功能性的字丟進最弱的那一層，
 *   整片畫面就會看起來發灰。
 */
.what {
  font-size: 12.5px;
  color: var(--text-1);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.who {
  font-size: 11px;
  color: var(--text-2);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.empty {
  font-size: 12px;
  color: var(--text-2);
}
</style>
