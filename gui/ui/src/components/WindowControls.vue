<script setup>
import { onMounted, ref } from 'vue'
import { Minus, Square, Copy, X } from 'lucide-vue-next'
import { api } from '../bridge'

const maximized = ref(false)

onMounted(async () => {
  maximized.value = await api.win.isMaximized()
})

// ⚠ 最大化狀態每次重新查詢，不自己記旗標。
const minimize = () => api.win.minimize()
const toggle = async () => {
  await api.win.toggleMaximize()
  maximized.value = await api.win.isMaximized()
}
const close = () => api.win.close()
</script>

<template>
  <!-- ⚠ 標題列整條是拖曳區，按得到的元件都要加 .no-drag。 -->
  <div class="no-drag flex items-stretch">
    <button class="ctl" title="最小化" @click="minimize">
      <Minus :size="15" />
    </button>
    <button class="ctl" :title="maximized ? '還原' : '最大化'" @click="toggle">
      <Copy v-if="maximized" :size="13" />
      <Square v-else :size="12" />
    </button>
    <button class="ctl close" title="關閉" @click="close">
      <X :size="16" />
    </button>
  </div>
</template>

<style scoped>
/*
 * ⚠ 不用全站的圓角與內距：46px 寬、滿高、貼到最右邊（最大化時「關閉」在螢幕角落，Fitts 定律）。
 */
.ctl {
  display: grid;
  place-items: center;
  width: 46px;
  border: 0;
  background: transparent;
  color: var(--text-1);
  cursor: pointer;
  transition: background 0.12s, color 0.12s;
}
.ctl:hover {
  background: var(--bg-3);
  color: var(--text-0);
}
/* 關閉鍵的 hover 用紅底白字（Windows 慣例） */
.ctl.close:hover {
  background: var(--red);
  color: #fff;
}
</style>
