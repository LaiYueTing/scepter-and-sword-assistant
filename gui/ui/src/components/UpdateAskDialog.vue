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
 * 查到新版時當場問「要不要現在更新」。
 *
 * ⚠ **只把按鈕點亮是不夠的。** 那顆是沒有文字的圖示鈕，它的職責會從「檢查更新」
 *   悄悄換成「更新到 vX」，而唯一的提示是一則三秒的 toast——使用者按下去得到的
 *   是「跳個字然後沒事」，要再按一次才會下載。實際回報就是這一句。
 *
 * ⚠ **自動查到也要問**（開視窗那一次）。看不到那顆按鈕的人（縮在系統匣、視窗
 *   一掛好幾天）否則會一直用著舊版，而舊版可能正帶著已經修好的問題。
 *
 * ⚠ **但不做成不能拒絕。** 更新器自己就出過「換檔成功但新版開不起來」的 bug，
 *   真的強制的話對方連退回舊版的機會都沒有。按「稍後再說」按鈕就留在
 *   「更新到 vX」的狀態，隨時可以再按。
 *
 * ⚠ 形狀與文案跟著 UpdateDialog（裝完問重啟的那個）走：標題是**現在是什麼狀態**、
 *   問句是「新版本 vX ⋯，是否⋯？」、按鈕左「稍後再說」右「立即⋯」。
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
        <!-- ⚠ 換行會變成一個空白：「（77 MB） 已釋出」中間就多一格。中文句子裡
             不能有那一格，所以整句寫在同一行。 -->
        <p class="q">新版本 <b>v{{ version }}</b><span v-if="size">（{{ size }}）</span>已釋出，是否立即更新？</p>
        <!--
          ⚠ 這兩句是**選「稍後再說」的代價**，不是在重述按鈕。UpdateDialog 那邊
            刻意不補說明，因為「重新啟動只是關掉再開」本來就知道；而「有待安裝的
            更新時開始執行是鎖住的」不講就不會知道——使用者正是為此問「他也要更新
            才能執行呀」。
        -->
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
  /* ⚠ 這裡有問句加一行說明，圖示要對齊**第一行**（和 CloseDialog 同理）；
       UpdateDialog 只有一行問句才用 center。 */
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
  line-height: 1.6;
  color: var(--text-2);
}
.foot {
  display: flex;
  align-items: center;
  gap: 8px;
}
</style>
