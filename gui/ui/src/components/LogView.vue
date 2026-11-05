<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { DynamicScroller, DynamicScrollerItem } from 'vue-virtual-scroller'
import { NDropdown, NInput, NSwitch, NTooltip, useMessage } from 'naive-ui'
import { Eraser, FilterX, ScrollText, Search } from 'lucide-vue-next'
import { useLogStore } from '../stores/logs'
import { useHostStore } from '../stores/host'

const logs = useLogStore()
const host = useHostStore()
const message = useMessage()
const scroller = ref(null)
const body = ref(null)

const rows = computed(() => logs.visible)

// 新的一行進來就捲到底，除非關閉「跟隨」
watch(
  () => rows.value.length,
  async () => {
    if (!logs.follow) return
    await nextTick()
    scroller.value?.scrollToBottom?.()
  }
)

/**
 * ⚠ 一般訊息不內嵌顏色，繼承 CSS 變數才會跟著主題。警告與錯誤用 token。
 */
function toneOf(level) {
  if (level === '錯誤') return 'bad'
  if (level === '警告') return 'warn'
  if (level === '等待') return 'muted'
  return ''
}

/* ══════════════════════════════════════════════════════════════════════
   右鍵選單
   ══════════════════════════════════════════════════════════════════════ */

const menu = ref({ show: false, x: 0, y: 0, row: null, sel: '' })

/**
 * ⚠ 在按下右鍵時就存下選取的文字：點選單項目時瀏覽器會清除選取範圍。
 */
function onContextMenu(e, row) {
  e.preventDefault()
  const sel = String(window.getSelection() || '')
  menu.value = { show: true, x: e.clientX, y: e.clientY, row: row || null, sel }
}

const options = computed(() => {
  const sel = menu.value.sel.trim().length > 0
  return [
    { label: '複製選取的內容', key: 'copy-sel', disabled: !sel },
    { label: '複製這一行', key: 'copy-row', disabled: !menu.value.row },
    { label: '全選', key: 'select-all' },
    { label: `複製全部（${rows.value.length} 行）`, key: 'copy-all', disabled: !rows.value.length },
    { type: 'divider', key: 'd1' },
    { label: '清掉篩選', key: 'clear-tags', disabled: !logs.filtering },
    { label: '清空畫面', key: 'clear' },
    { type: 'divider', key: 'd2' },
    { label: '開啟日誌資料夾', key: 'reveal' }
  ]
})

const lineText = (r) => `[${r.time}] [${r.level}] ${r.module} ${r.msg}`

/**
 * 複製到剪貼簿。
 *
 * ⚠ `file://` 不是安全內容，`navigator.clipboard` 是 undefined，用 `execCommand('copy')` 當退路。
 */
async function copy(text) {
  if (!text) return
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
    } else {
      const ta = document.createElement('textarea')
      ta.value = text
      // 放在畫面外，不影響捲動位置
      ta.style.cssText = 'position:fixed;left:-9999px;top:0;opacity:0'
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      ta.remove()
    }
    message.success('已複製')
  } catch (e) {
    message.error(`複製失敗：${e.message}`)
  }
}

function selectAll() {
  const el = body.value
  if (!el) return
  const range = document.createRange()
  range.selectNodeContents(el)
  const sel = window.getSelection()
  sel.removeAllRanges()
  sel.addRange(range)
}

function onSelect(key) {
  menu.value.show = false
  switch (key) {
    case 'copy-sel':
      copy(menu.value.sel)
      break
    case 'copy-row':
      copy(lineText(menu.value.row))
      break
    case 'select-all':
      /*
       * ⚠ 虛擬捲動只選得到畫出來的行，整份用「複製全部」（從 store 取）。
       */
      selectAll()
      break
    case 'copy-all':
      copy(rows.value.map(lineText).join('\n'))
      break
    case 'clear-tags':
      logs.clearTags()
      break
    case 'clear':
      logs.clear()
      break
    case 'reveal':
      host.reveal('logs')
      break
  }
}
</script>

<template>
  <div class="card flex flex-col" style="min-height: 0">
    <div class="pane-hd" style="flex-direction: column; align-items: stretch; gap: 8px">
      <div class="hd-row">
        <ScrollText :size="15" style="color: var(--accent-text)" />
        <span class="hd-title">
          <span class="t">日誌</span>
          <span class="s">{{ logs.lines.length }} 行</span>
        </span>
        <span v-if="logs.counts.error" class="nc-pill nc-pill--bad">
          <span>{{ logs.counts.error }} 錯誤</span>
        </span>
        <span v-if="logs.counts.warn" class="nc-pill nc-pill--warn">
          <span>{{ logs.counts.warn }} 警告</span>
        </span>

        <div class="flex-1"></div>

        <NInput
          v-model:value="logs.filter"
          size="tiny"
          clearable
          placeholder="搜尋訊息"
          style="width: 150px"
        >
          <template #prefix><Search :size="13" /></template>
        </NInput>

        <NTooltip trigger="hover">
          <template #trigger>
            <div class="flex items-center gap-1.5">
              <NSwitch v-model:value="logs.follow" size="small" />
              <span style="font-size: 12.5px; color: var(--text-1)">跟隨</span>
            </div>
          </template>
          跟隨最新一行：開啟時自動捲到底
        </NTooltip>

        <button class="iconbtn" title="清空畫面（日誌檔不受影響）" @click="logs.clear()">
          <Eraser :size="14" />
        </button>
      </div>

      <!-- 類別篩選：只列出現過的標籤，沒有選取表示不過濾。 -->
      <div v-if="logs.lines.length" class="tags">
        <button
          v-for="t in logs.tags.levels"
          :key="'L' + t.name"
          class="nc-tag"
          :class="[{ on: logs.levels.includes(t.name) }, 'lv-' + toneOf(t.name)]"
          @click="logs.toggle('levels', t.name)"
        >
          {{ t.name }}<span class="num">{{ t.count }}</span>
        </button>

        <span v-if="logs.tags.modules.length > 1" class="divider"></span>

        <button
          v-for="t in logs.tags.modules"
          :key="'M' + t.name"
          class="nc-tag"
          :class="{ on: logs.modules.includes(t.name) }"
          @click="logs.toggle('modules', t.name)"
        >
          {{ t.name }}<span class="num">{{ t.count }}</span>
        </button>

        <button
          v-if="logs.filtering"
          class="iconbtn"
          style="width: 24px; height: 22px"
          title="清掉所有篩選"
          @click="logs.clearTags()"
        >
          <FilterX :size="13" />
        </button>
      </div>
    </div>

    <!-- 空狀態用 absolute 蓋滿同一格再置中。 -->
    <div
      ref="body"
      class="body flex-1 selectable"
      style="min-height: 0"
      @contextmenu="onContextMenu($event, null)"
    >
      <div v-if="!rows.length" class="empty">
        <ScrollText :size="34" class="empty-i" />
        <span>{{ logs.lines.length ? '這些條件下沒有日誌' : '還沒有日誌' }}</span>
        <span class="hint">
          {{ logs.lines.length ? '按上面的標籤或清掉篩選' : '按「開始執行」之後這裡會即時更新' }}
        </span>
      </div>

      <DynamicScroller
        v-else
        ref="scroller"
        :items="rows"
        :min-item-size="22"
        key-field="id"
        class="h-full"
      >
        <template #default="{ item, index, active }">
          <DynamicScrollerItem
            :item="item"
            :active="active"
            :data-index="index"
            :size-dependencies="[item.msg]"
          >
            <div class="row" :class="toneOf(item.level)" @contextmenu.stop="onContextMenu($event, item)">
              <span class="time">{{ item.time }}</span>
              <span class="mod">{{ item.module }}</span>
              <span class="msg">{{ item.msg }}</span>
            </div>
          </DynamicScrollerItem>
        </template>
      </DynamicScroller>
    </div>


    <NDropdown
      trigger="manual"
      placement="bottom-start"
      :show="menu.show"
      :x="menu.x"
      :y="menu.y"
      :options="options"
      @select="onSelect"
      @clickoutside="menu.show = false"
    />
  </div>
</template>

<style scoped>
.body {
  position: relative;
}

/* 空狀態：鋪滿整格再置中 */
.empty {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  color: var(--text-1);
  font-size: 13.5px;
  user-select: none;
}
.empty .hint {
  font-size: 12px;
  color: var(--text-2);
}
.empty-i {
  color: var(--accent-text);
  opacity: 0.55;
}

.tags {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}
/* 等級標籤帶自己的顏色 */
.nc-tag.lv-bad {
  color: var(--red);
  border-color: color-mix(in srgb, var(--red) 45%, transparent);
}
.nc-tag.lv-warn {
  color: var(--amber);
  border-color: color-mix(in srgb, var(--amber) 45%, transparent);
}
.divider {
  width: 1px;
  height: 14px;
  margin: 0 2px;
  background: var(--border);
}

/*
 * 比例字型，用顏色分欄：時間淡、模組用提示色、訊息最明顯。
 */
.row {
  display: grid;
  grid-template-columns: 110px 78px 1fr;
  gap: 8px;
  padding: 2px 12px;
  font-size: 13px;
  line-height: 1.6;
  align-items: baseline;
}
.row:hover {
  background: var(--bg-3);
}
.time {
  color: var(--text-2);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.mod {
  color: var(--accent-text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
/*
 * ⚠ 多行訊息用懸掛縮排：負的 text-indent 配同寬的 padding-left。
 */
.msg {
  white-space: pre-wrap;
  word-break: break-word;
  padding-left: 1.4em;
  text-indent: -1.4em;
  color: var(--text-0);
}
.row.bad .msg {
  color: var(--red);
}
.row.warn .msg {
  color: var(--amber);
}
.row.muted .msg {
  color: var(--text-1);
}
</style>
