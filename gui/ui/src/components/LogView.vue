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

// 新的一行進來就捲到底，除非使用者自己往回翻了（關掉「跟著捲」）
watch(
  () => rows.value.length,
  async () => {
    if (!logs.follow) return
    await nextTick()
    scroller.value?.scrollToBottom?.()
  }
)

/**
 * ⚠ **一般訊息不要內嵌顏色**，讓它繼承 CSS 變數。內嵌的話切換主題之後，早先寫進去
 *   的幾百行會留在舊配色上。警告與錯誤才用 token——那兩個在每套配色下都夠顯眼。
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
 * ⚠ **選取的文字要在按下右鍵的那一刻就抄下來，不能等按了選單才去讀。**
 *   點選單項目時瀏覽器會把整份文件的選取範圍收掉——等 `onSelect` 跑起來，
 *   `window.getSelection()` 已經是空的了。症狀就是使用者說的「按了沒有用」：
 *   選單看得到、項目也不是灰的（那時選取還在），按下去卻什麼都沒複製到。
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
 * ⚠ **不能只用 `navigator.clipboard`。** 網頁版是用 `file://` 載入的，而那**不是
 *   安全內容**——`navigator.clipboard` 在那裡是 `undefined`，呼叫下去會丟例外而
 *   「按了沒反應」。舊的 `execCommand('copy')` 沒有這個限制，所以拿它當退路。
 */
async function copy(text) {
  if (!text) return
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
    } else {
      const ta = document.createElement('textarea')
      ta.value = text
      // 放在畫面外，否則捲動位置會被搶走
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
       * ⚠ **虛擬捲動只選得到「畫出來的那幾行」。** 這不是 bug，是虛擬捲動的本質
       *   ——沒捲到的行根本不在 DOM 裡。真的要整份就按「複製全部」，那條是從
       *   store 拿的，不受畫面影響。
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

      <!--
        類別篩選。⚠ **只列出現過的標籤**，而且「不選 = 不過濾」（不是「全部排除」）
        ——固定列出所有等級與模組的話，畫面上會有一排永遠是 0 的東西，而這個面板的
        重點是「今天實際發生了什麼」。
      -->
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

    <!--
      ⚠ **空狀態要放在同一層裡置中，不能接在捲動區後面。** 接在後面的話它是「內容
        之後的一段文字」，會貼在面板上緣底下一點的位置——使用者看到的是「偏下」而
        不是「置中」（其實是偏上）。用 `position: absolute` 蓋滿同一格才置得中。
    -->
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

/* 空狀態：鋪滿整格再置中，而不是「接在內容後面的一段文字」 */
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
/*
 * 圖示慢慢浮動。⚠ 幅度刻意很小（3px、4.2 秒）：這是一塊**空面板**，動畫的用途是
 * 「這裡是活的、只是還沒東西」，不是要吸引注意力。
 */
.empty-i {
  color: var(--accent-text);
  opacity: 0.55;
  animation: empty-float 4.2s ease-in-out infinite;
}
@keyframes empty-float {
  0%,
  100% {
    transform: translateY(0);
    opacity: 0.45;
  }
  50% {
    transform: translateY(-3px);
    opacity: 0.7;
  }
}
@media (prefers-reduced-motion: reduce) {
  .empty-i {
    animation: none;
  }
}

.tags {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}
/* 等級標籤帶自己的顏色，掃一眼就知道哪個是錯誤 */
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
 * ⚠ **不要沿用終端機那份欄位對齊。** 那是為等寬字型設計的（`logger.pad()` 按顯示
 *   寬度補空白），這裡是比例字型，補空白只會歪。改用顏色分欄：時間淡、模組是提示色、
 *   訊息才是主角。
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
 * ⚠ **多行訊息要用懸掛縮排，不能補空白字元。** 連線失敗那段有七行提示，補
 *   `&nbsp;` 在比例字型下永遠對不齊——那是等寬字型的排版思維。負的 text-indent
 *   配同寬的 padding-left 才會讓第二行以後對齊到訊息欄的左緣，而且**順帶把自動
 *   折行也一起修好**：長訊息折到第二行時本來也會跑回最左邊。
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
