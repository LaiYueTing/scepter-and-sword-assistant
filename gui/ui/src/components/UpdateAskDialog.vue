<script setup>
import { computed } from 'vue'
import { NButton, NModal } from 'naive-ui'
import { ArrowDownToLine } from 'lucide-vue-next'
import { useHostStore } from '../stores/host'

const props = defineProps({ show: Boolean })
const emit = defineEmits(['update:show'])

const host = useHostStore()
const version = computed(() => host.update?.version || '')
const size = computed(() => host.update?.size_text || '')

/**
 * 查到新版時詢問是否現在更新，自動查詢也一樣。
 *
 * ⚠ 可以拒絕：按「稍後再說」後按鈕維持「更新到 vX」。
 * 文案格式同 UpdateDialog：標題寫現在的狀態，問句「新版本 vX ⋯，是否⋯？」。
 */

async function choose(now) {
  emit('update:show', false)
  if (!now) return
  try {
    await host.applyUpdate()
  } catch (e) {
    host.status = `更新失敗：${e.message}`
  }
}
</script>

<template>
  <NModal
    :show="show"
    preset="card"
    style="width: 460px"
    title="偵測到新版本"
    :bordered="false"
    :closable="false"
    :mask-closable="false"
    @update:show="(v) => emit('update:show', v)"
  >
    <div class="ask">
      <span class="ic"><ArrowDownToLine :size="20" /></span>
      <div>
        <!-- ⚠ 整句寫在同一行，模板換行會變成空白。 -->
        <p class="q">新版本 <b>v{{ version }}</b><span v-if="size">（{{ size }}）</span>已釋出，是否立即更新？</p>
        <!-- 選「稍後再說」的代價：更新之前不能開始執行。 -->
        <p class="sub">更新之前不能開始執行。裝完會問你要不要重新啟動。</p>
      </div>
    </div>

    <template #footer>
      <div class="foot">
        <div class="flex-1"></div>
        <NButton size="small" @click="choose(false)">稍後再說</NButton>
        <NButton size="small" type="primary" @click="choose(true)">
          <template #icon><ArrowDownToLine :size="15" /></template>
          立即更新
        </NButton>
      </div>
    </template>
  </NModal>
</template>

<style scoped>
.ask {
  display: flex;
  gap: 12px;
  /* 問句加一行說明，圖示對齊第一行。 */
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
  line-height: 1.6;
  color: var(--text-2);
}
.foot {
  display: flex;
  align-items: center;
  gap: 8px;
}
</style>
