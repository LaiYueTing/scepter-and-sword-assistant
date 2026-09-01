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

/*
 * 依腳本分組。
 *
 * ⚠ 每一列都重複寫一次腳本名的話，列高會變成兩行——十個項目就只看得到三個，
 *   其餘都要捲。分組之後每個腳本只佔一行標題，列本身收成單行。
 */
const groups = computed(() => {
  const out = []
  for (const r of rows.value) {
    if (!out.length || out[out.length - 1].task !== r.task) {
      out.push({ task: r.task, items: [] })
    }
    out[out.length - 1].items.push(r)
  }
  return out
})

/*
 * ⚠ 沒有上限的那些**不要用最弱的那一層**。次數是功能性資訊，讀者每次都要看，
 *   而 `--off` 是留給「已經不算數了」的（腳本裡已經沒有這條規則）。有沒有上限
 *   從 `4` 和 `0 / 3` 的寫法就分得出來，不必再用顏色講一次。
 */
function tone(r) {
  if (r.stale) return 'nc-pill--off'
  return r.limit && r.done >= r.limit ? 'nc-pill--ok' : 'nc-pill--idle'
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
    <div class="flex flex-col gap-1 px-3 py-2" style="overflow: auto; min-height: 0">
      <!--
        ⚠ **這裡不是「今天跑過哪些腳本」。** 列出來的是**答案不在畫面上**的那幾件事
          （打過幾場競技場、捐了幾次晨星、買了幾次領獎次數）。次數用盡、獎勵已領
          這些腳本進遊戲看得出來，本來就不需要記。
      -->
      <p v-if="!rows.length" class="empty">今天還沒有任何計數。</p>

      <template v-for="g in groups" :key="g.task">
        <div class="who">{{ g.task }}</div>

        <div v-for="r in g.items" :key="r.key" class="dc-row">
          <div class="what">
            {{ r.label }}
            <span v-if="r.stale" class="gone">已不在腳本裡</span>
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
              <button class="iconbtn dc-reset" :disabled="locked || !r.done"
                      title="把這一項今天的計數歸零">
                <RotateCcw :size="13" />
              </button>
            </template>
            重設之後這一項今天會重新計算，可能再花掉一次資源。
          </NPopconfirm>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
/*
 * ⚠ **`flex: none` 不是裝飾。** 這一塊是會溢出的直向 flex 欄，而 flex 項目預設
 *   可以被壓縮——`.who` 有 `overflow: hidden`，於是它被壓成**高度 0**：分組標題
 *   在畫面上完全消失，而 DOM 裡是好好的（文字、顏色、字級都對）。看程式碼看不
 *   出來，要量 `getBoundingClientRect().height` 才知道。
 */
.dc-row,
.who {
  flex: none;
}

.dc-row {
  display: grid;
  grid-template-columns: 1fr auto auto;
  align-items: center;
  gap: 8px;
  padding-left: 8px;      /* 縮排到腳本名底下，一眼看得出誰屬於誰 */
}

/* 重設鍵縮一級：它決定整列的高度，而這一塊要盡量多塞幾列。 */
.dc-reset {
  width: 22px;
  height: 22px;
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
/* 分組標題（腳本名）。這一層是「它屬於誰」，才用最弱的那一層。 */
.who {
  font-size: 11px;
  color: var(--text-2);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-top: 2px;
}
.who:not(:first-child) {
  margin-top: 6px;
}
/* 狀態檔裡還留著、但腳本已經沒有這條規則了（改過名、關掉的開關）。 */
.gone {
  font-size: 10.5px;
  color: var(--text-2);
  margin-left: 4px;
}
.empty {
  font-size: 12px;
  color: var(--text-2);
}
</style>
