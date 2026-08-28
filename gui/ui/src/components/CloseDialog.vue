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
 * ⚠ **這個對話框是自繪的，不用系統原生的。** 系統彈窗是強制回應的，會把整個
 *   視窗凍住——而按下「直接結束」之後還要跑 10 秒的收尾，那段期間狀態列與日誌
 *   面板都要繼續更新。用文字說明「不是當掉」，卻被自己造成的當掉蓋掉，是同一
 *   條路上最容易犯的錯。
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
    <!--
      ⚠ **問句要把兩個選項都講出來**（「結束，還是縮到系統匣」），不要只問
        「要結束嗎？」。後者把「縮到系統匣」變成一個要自己在按鈕列上發現的東西，
        而那才是這個對話框存在的理由——執行中直接結束會中斷正在打的副本。
    -->
    <div class="ask">
      <span class="ic"><Power :size="20" /></span>
      <div>
        <p class="q">要結束程式，還是縮到系統匣繼續在背景執行？</p>
        <p class="sub">
          縮到系統匣後，<b>排程與腳本會繼續執行</b>，點右下角的圖示可以叫回視窗。
        </p>
        <p v-if="host.running" class="sub warn">
          腳本正在執行中：選「直接結束」會先跑完收尾動作（逐層退回家園），約需 10 秒。
        </p>
      </div>
    </div>

    <!--
      ⚠ **對齊交給版面，不要用 em 去推別的元件的尺寸。** 說明的字級比標籤小，
        同樣的 `em` 換算出來比較短——原本寫 `margin-left: 1.85em`，說明反而跑到
        標籤的左邊去。這裡的作法是把說明**放進 NCheckbox 自己的內容區**，
        對齊由它負責，我們一個像素都不必推算。
    -->
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
/* 對話框的圖示：主色淡底的圓角方塊。全站的對話框用同一種形狀。 */
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
 * ⚠ **兩行的標籤要讓核取方塊對齊「第一行」，不是整塊的垂直中央。** naive-ui 的
 *   核取方塊預設是 `align-items: center`，標籤一變成兩行，方塊就掉到兩行中間。
 *   把方塊那一格改成靠上、再用和第一行同高的 `min-height` 把它推回那一行的中線。
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
