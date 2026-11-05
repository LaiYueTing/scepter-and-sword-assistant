<script setup>
import { computed, onMounted, watch } from 'vue'
import { NPopconfirm, NTooltip, useMessage } from 'naive-ui'
import { CalendarCheck, RotateCcw } from 'lucide-vue-next'
import { useHostStore } from '../stores/host'

const host = useHostStore()
const message = useMessage()

// 執行中不可重設：引擎在建立時就讀入計數。
const locked = computed(() => host.running || host.closing)
const rows = computed(() => host.daily.rows)
const anything = computed(() => rows.value.some((r) => r.done > 0))

/*
 * 依腳本分組，每個腳本只佔一行標題。
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
 * 次數是功能性資訊，不用最弱的文字色；`--off` 只給腳本已經沒有的規則。
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

// 腳本開始或結束時重讀計數。
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

    <!-- ⚠ 直向內距用 `py-2`：這塊與模擬器面板共用一欄，`p-3` 會多 4px 而出現捲軸。 -->
    <div class="flex flex-col gap-1 px-3 py-2" style="overflow: auto; min-height: 0">
      <!-- 列出畫面上讀不到的計數（競技場場次、晨星捐獻、買領獎次數）。 -->
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
 * ⚠ `flex: none` 不可省略：`.who` 有 `overflow: hidden`，在溢出的直向 flex 欄裡會被壓成高度 0。
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
  padding-left: 8px;      /* 縮排到腳本名底下 */
}

/* 重設鍵縮小一級，它決定整列的高度。 */
.dc-reset {
  width: 22px;
  height: 22px;
}

/*
 * 項目名稱用 `--text-1`，腳本名用 `--text-2`。
 */
.what {
  font-size: 12.5px;
  color: var(--text-1);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
/* 分組標題（腳本名） */
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
/* 狀態檔裡還有、但腳本已經沒有這條規則。 */
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
