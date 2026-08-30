<script setup>
import { NButton, NModal } from 'naive-ui'
import { RefreshCw } from 'lucide-vue-next'
import { useHostStore } from '../stores/host'

const props = defineProps({ show: Boolean, version: String })
const emit = defineEmits(['update:show'])

const host = useHostStore()

/**
 * 換好檔之後問使用者要不要現在重新啟動。
 *
 * ⚠ **一定要問，而且問完才排重啟。** 換檔本身只是把新的 EXE 放到位，畫面上
 *   完全沒有反應——使用者的回報就是「他不會 UI 跳出來詢問是否重啟嗎?」。
 *   而排重啟的背景工作是「等這個行程結束就啟動新版」，先排後問的話它會一直
 *   潛伏著，等使用者哪天關掉程式就自己跳出來，還可能撞上他自己開的那次而被
 *   防多開擋成「助手已經在執行中」。
 *
 * ⚠ **形狀跟著 CloseDialog 走**（自繪的 NModal、主色淡底的圓角圖示、按鈕帶
 *   圖示）。用 naive-ui 的 `dialog.success()` 會把主要按鈕染成綠色，而綠色在
 *   這套介面裡是**狀態語意**（好／執行中），不是「這是主要動作」的意思。
 */

async function choose(now) {
  emit('update:show', false)
  if (!now) return
  try {
    await host.call('update_restart')
  } catch (e) {
    host.status = `重新啟動失敗：${e.message}`
  }
}
</script>

<template>
  <NModal
    :show="show"
    preset="card"
    style="width: 460px"
    title="更新完成"
    :bordered="false"
    :closable="false"
    :mask-closable="false"
    @update:show="(v) => emit('update:show', v)"
  >
    <!--
      ⚠ **不要補說明。** 「重新啟動只是關掉再開」是使用者本來就知道的，
        「選稍後也不會漏掉這一版」則是按鈕名稱自己就講完的——寫上去只是讓
        他多讀兩行。CloseDialog 那邊有說明，是因為「縮到系統匣」真的需要
        解釋（排程會繼續跑、圖示在哪裡叫回來）。
    -->
    <div class="ask">
      <span class="ic"><RefreshCw :size="20" /></span>
      <div>
        <p class="q">
          新版本 <b>v{{ version }}</b> 已就緒，是否重新啟動進行更新？
        </p>
      </div>
    </div>

    <template #footer>
      <div class="foot">
        <div class="flex-1"></div>
        <NButton size="small" @click="choose(false)">稍後再說</NButton>
        <NButton size="small" type="primary" @click="choose(true)">
          <template #icon><RefreshCw :size="15" /></template>
          立即重新啟動
        </NButton>
      </div>
    </template>
  </NModal>
</template>

<style scoped>
.ask {
  display: flex;
  gap: 12px;
  /*
   * ⚠ 這裡用 center，而 CloseDialog 用 flex-start——差別在**文字有幾行**。
   *   那邊有問句加兩行說明，圖示要對齊「第一行」；這裡只有一行問句，靠上
   *   對齊會讓文字浮在 40px 圖示的上緣。
   */
  align-items: center;
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
.foot {
  display: flex;
  align-items: center;
  gap: 8px;
}
</style>
