<script setup>
import { NButton, NModal } from 'naive-ui'
import { RefreshCw } from 'lucide-vue-next'
import { useHostStore } from '../stores/host'

const props = defineProps({ show: Boolean, version: String })
const emit = defineEmits(['update:show'])

const host = useHostStore()

/**
 * 換檔完成後詢問是否重新啟動。
 *
 * ⚠ 問完才排定重新啟動（`restart()` 等的是這個行程結束）。
 * ⚠ 用自繪的 NModal：`dialog.success()` 的綠色在這套介面是狀態語意。
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
   * 只有一行問句，圖示置中（CloseDialog 有多行才靠上）。
   */
  align-items: center;
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
.foot {
  display: flex;
  align-items: center;
  gap: 8px;
}
</style>
