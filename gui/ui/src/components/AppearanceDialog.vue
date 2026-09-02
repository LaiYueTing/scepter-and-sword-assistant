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
 * 174 組全部畫出來不會慢（都是純 CSS 漸層的方塊），但**捲不完**——所以給一個
 * 搜尋框。中英文都比對：名字記不住的時候，記得的往往是 "sunset" 那個英文字。
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
      ⚠ **每一列都是「名稱 ／ 一行說明 ／ 控制項」的同一種形狀，說明一律以
        『套用範圍：』起頭。** 這個對話框以後還會長，格式先固定下來：說明長短不一、
        有的有有的沒有的話，讀者每一列都得重新找一次「控制項在哪」。
      ⚠ 說明寫的是**這個選項控制什麼**，不是「這次改了什麼」——後者兩週後就過期了。
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

      <!--
        關閉行為。
        ⚠ **它屬於這裡，不屬於「玩法設定」。** 判準是存在哪裡：`config.yaml` 是
          腳本行為，`ui.json` 是視窗長什麼樣、怎麼關——兩份東西不該混在同一個
          對話框裡按同一顆儲存。
      -->
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
    </div>

    <!--
      ⚠ 明暗切換**不放在這裡**，它在標題列那顆月亮／太陽上。那是每天會按好幾次的
        東西，藏進一個要先打開的對話框裡等於降級。
      ⚠ **不補一行 footer 去說明這件事。** 那句話每次開都要再讀一遍，而它講的是
        「別的東西在哪裡」——放不下的資訊應該讓那顆按鈕自己的 tooltip 去講。
    -->
  </NModal>
</template>

<style scoped>
.rows {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/*
 * ⚠ **對齊交給版面，不要用 em 去推別的元件的尺寸。** 說明文字的字級比標題小，
 *   同樣的 `em` 換算出來比較短，補 `margin-left` 只會讓說明跑到標題左邊去。
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
/* 補充說明才用 --text-2；欄位標題一律 --text-1 以上 */
.s {
  margin-top: 3px;
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--text-2);
}

/* `QFrame::HLine` 那個坑的網頁版：分隔線用 1px 高的 div，不要 border 疊 border */
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
/* 選中的用最強的文字色描邊——漸層什麼顏色都有可能，主色描邊會在某些主題上消失 */
.swatch.on {
  border-color: var(--text-0);
}

/*
 * ⚠ 名字底下那條半透明黑帶是必要的：色塊可能是淺黃或近白（`wg18`、`wg50`），
 *   白字直接放上去會整段看不見。
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
