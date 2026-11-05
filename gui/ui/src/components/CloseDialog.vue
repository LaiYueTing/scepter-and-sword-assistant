<script setup>
import { ref } from 'vue'
import { NButton, NCheckbox, NModal } from 'naive-ui'
import { MinusSquare, Power } from 'lucide-vue-next'
import { useHostStore } from '../stores/host'
import { useUiStore } from '../stores/ui'
import { api } from '../bridge'

const props = defineProps({ show: Boolean })
const emit = defineEmits(['update:show'])

const host = useHostStore()
const ui = useUiStore()
const remember = ref(false)

/**
 * ⚠ 自繪對話框，不用系統原生的：強制回應會凍結視窗，而結束程序期間介面要繼續更新。
 */

async function choose(action) {
  if (action === 'cancel') {
    emit('update:show', false)
    return
  }
  if (remember.value) await ui.setOnClose(action)
  emit('update:show', false)
  if (action === 'tray') api.app.hide()
  else api.app.quit()
}
</script>

<template>
  <NModal
    :show="show"
    preset="card"
    class="close-dialog"
    style="width: 460px"
    title="關閉杖劍傳說助手"
    :bordered="false"
    :closable="false"
    :mask-closable="false"
    @update:show="(v) => emit('update:show', v)"
  >
    <!-- 問句要寫出兩個選項：結束，或縮到系統匣。 -->
    <div class="ask">
      <span class="ic"><Power :size="20" /></span>
      <div>
        <p class="q">要結束程式，還是縮到系統匣繼續在背景執行？</p>
        <p class="sub">
          縮到系統匣後，<b>排程與腳本會繼續執行</b>，點右下角的圖示可以叫回視窗。
        </p>
        <p v-if="host.running" class="sub warn">
          腳本正在執行中：選「直接結束」會先跑完結束程序（逐層退回家園），約需 15 秒。
        </p>
      </div>
    </div>

    <!-- 說明放在 NCheckbox 的內容區，對齊由元件處理。 -->
    <NCheckbox v-model:checked="remember" class="remember">
      <div>記住我的選擇，下次不要再問</div>
      <div class="hint">之後在標題列的調色盤圖示 →「按下視窗的 ✕ 時」改得回來</div>
    </NCheckbox>

    <template #footer>
      <div class="foot">
        <NButton size="small" @click="choose('cancel')">取消</NButton>
        <div class="flex-1"></div>
        <NButton size="small" @click="choose('quit')">
          <template #icon><Power :size="15" /></template>
          直接結束
        </NButton>
        <NButton size="small" type="primary" @click="choose('tray')">
          <template #icon><MinusSquare :size="15" /></template>
          縮到系統匣
        </NButton>
      </div>
    </template>
  </NModal>
</template>

<style scoped>
.ask {
  display: flex;
  gap: 12px;
  align-items: flex-start;
}
/* 對話框的圖示：主色淡底的圓角方塊 */
.ic {
  width: 40px;
  height: 40px;
  flex: none;
  border-radius: 11px;
  display: grid;
  place-items: center;
  background: var(--accent-soft);
  color: var(--accent-text);
}
.q {
  margin: 0;
  line-height: 1.6;
  color: var(--text-0);
}
.sub {
  margin: 6px 0 0;
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--text-2);
}
.sub.warn {
  color: var(--amber);
}

.remember {
  margin-top: 16px;
  align-items: flex-start;
}
/*
 * ⚠ 兩行的標籤，核取方塊要對齊第一行：naive-ui 預設 `align-items: center`，
 *   方塊靠上，再用和第一行同高的 `min-height` 對齊中線。
 */
.remember :deep(.n-checkbox-box-wrapper) {
  display: flex;
  align-items: center;
  align-self: flex-start;
  min-height: 22px;
}
.remember :deep(.n-checkbox__label) {
  padding-top: 0;
  padding-bottom: 0;
  line-height: 22px;
}
.hint {
  margin-top: 3px;
  font-size: 12px;
  line-height: 1.6;
  color: var(--text-2);
}

.foot {
  display: flex;
  align-items: center;
  gap: 8px;
}
</style>
