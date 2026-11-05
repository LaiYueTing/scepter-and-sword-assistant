<script setup>
import { computed, ref } from 'vue'
import { NInput, NModal } from 'naive-ui'
import { Search } from 'lucide-vue-next'
import { BG_THEMES, bgSwatch } from '../data/gradients'
import { useUiStore } from '../stores/ui'

defineProps({ show: { type: Boolean, default: false } })
defineEmits(['update:show'])

const ui = useUiStore()
const keyword = ref('')

/**
 * 主題搜尋，比對中英文名稱。
 */
const list = computed(() => {
  const k = keyword.value.trim().toLowerCase()
  if (!k) return BG_THEMES
  return BG_THEMES.filter(
    (t) => t.name.includes(k) || t.en.toLowerCase().includes(k) || t.id === k
  )
})

const current = computed(() => BG_THEMES.find((t) => t.id === ui.bgTheme) || BG_THEMES[0])
</script>

<template>
  <NModal
    :show="show"
    preset="card"
    title="介面設定"
    style="width: 640px"
    :bordered="false"
    @update:show="(v) => $emit('update:show', v)"
  >
    <!--
      每一列的格式：名稱 ／ 一行說明 ／ 控制項。說明以「套用範圍：」起頭，寫這個選項控制什麼。
    -->
    <div class="rows">
      <!-- 背景主題 -->
      <section>
        <div class="hd">
          <div>
            <div class="k">背景主題</div>
            <div class="s">套用範圍：桌布、面板、卡片、框線、文字、主色。目前為「{{ current.name }}」。</div>
          </div>
          <NInput
            v-model:value="keyword"
            size="small"
            clearable
            placeholder="搜尋主題"
            style="width: 172px; flex: none"
          >
            <template #prefix><Search :size="13" /></template>
          </NInput>
        </div>

        <div class="swatches">
          <button
            v-for="t in list"
            :key="t.id"
            class="swatch"
            :class="{ on: ui.bgTheme === t.id }"
            :style="{ background: bgSwatch(t) }"
            :title="t.en && t.en !== t.name ? `${t.name}（${t.en}）` : t.name"
            @click="ui.setBgTheme(t.id)"
          >
            <span v-if="ui.bgTheme === t.id" class="tick">✓</span>
            <span class="name">{{ t.name }}</span>
          </button>
          <div v-if="!list.length" class="empty">找不到「{{ keyword }}」</div>
        </div>
      </section>

      <div class="rule"></div>

      <!-- 燈號 -->
      <section class="hd">
        <div>
          <div class="k">狀態燈號</div>
          <div class="s">套用範圍：已連線與執行中的指示燈。靜態仍會發光，只是不閃爍。</div>
        </div>
        <div class="nc-seg">
          <button :class="{ on: ui.glow === 'breathe' }" @click="ui.setGlow('breathe')">呼吸</button>
          <button :class="{ on: ui.glow === 'none' }" @click="ui.setGlow('none')">靜態</button>
        </div>
      </section>

      <div class="rule"></div>

      <!-- 關閉行為，存在 ui.json。 -->
      <section class="hd">
        <div>
          <div class="k">按下視窗的 ✕ 時</div>
          <div class="s">
            套用範圍：關閉視窗這個動作。縮到系統匣時排程繼續在背景執行，
            右下角的圖示可以叫回視窗（雙擊還原，右鍵有停止與結束）。
          </div>
        </div>
        <div class="nc-seg" style="flex: none">
          <button :class="{ on: ui.onClose === 'ask' }" @click="ui.setOnClose('ask')">每次問</button>
          <button :class="{ on: ui.onClose === 'tray' }" @click="ui.setOnClose('tray')">縮到系統匣</button>
          <button :class="{ on: ui.onClose === 'quit' }" @click="ui.setOnClose('quit')">直接結束</button>
        </div>
      </section>

      <div class="rule"></div>

      <!-- 縮到系統匣的通知。點通知也能關閉，但不一定收得到事件，這裡是可靠的入口。 -->
      <section class="hd">
        <div>
          <div class="k">縮到系統匣時提醒</div>
          <div class="s">
            套用範圍：縮到系統匣的那一刻。開啟時會跳一則通知說明程式還在背景執行。
            點那則通知也會關掉這個提醒。
          </div>
        </div>
        <div class="nc-seg" style="flex: none">
          <button :class="{ on: ui.trayHint }" @click="ui.setTrayHint(true)">提醒</button>
          <button :class="{ on: !ui.trayHint }" @click="ui.setTrayHint(false)">不提醒</button>
        </div>
      </section>
    </div>

  </NModal>
</template>

<style scoped>
.rows {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/*
 * 對齊交給版面，不用 em 推算別的元件的尺寸。
 */
.hd {
  display: flex;
  align-items: flex-start;
  gap: 16px;
}
.hd > :first-child {
  flex: 1;
  min-width: 0;
}
.k {
  font-weight: 600;
  font-size: 14px;
}
/* 補充說明用 --text-2，欄位標題用 --text-1 以上 */
.s {
  margin-top: 3px;
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--text-2);
}

/* 分隔線 */
.rule {
  height: 1px;
  background: var(--border);
}

.swatches {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(96px, 1fr));
  gap: 8px;
  max-height: 296px;
  overflow-y: auto;
  margin-top: 10px;
  padding: 2px 6px 2px 2px;
}

.swatch {
  position: relative;
  height: 48px;
  border-radius: 10px;
  border: 2px solid transparent;
  padding: 0;
  cursor: pointer;
  overflow: hidden;
  box-shadow: var(--shadow-card);
  transition: transform 0.12s ease, border-color 0.12s ease;
}
.swatch:hover {
  transform: translateY(-1px);
}
/* 選中的用最強的文字色描邊（主色描邊在某些主題上看不見） */
.swatch.on {
  border-color: var(--text-0);
}

/*
 * ⚠ 名字底下的半透明黑帶不可省略：色塊可能近白（`wg18`、`wg50`）。
 */
.name {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  padding: 2px 4px;
  font-size: 11px;
  color: #fff;
  text-align: center;
  background: rgb(0 0 0 / 42%);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.tick {
  position: absolute;
  top: 3px;
  right: 5px;
  font-size: 12px;
  font-weight: 700;
  color: #fff;
  text-shadow: 0 1px 3px rgb(0 0 0 / 70%);
}

.empty {
  grid-column: 1 / -1;
  padding: 18px 0;
  text-align: center;
  font-size: 12.5px;
  color: var(--text-2);
}

</style>
