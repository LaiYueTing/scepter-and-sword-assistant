<script setup>
import { onMounted, ref } from 'vue'
import { Minus, Square, Copy, X } from 'lucide-vue-next'
import { api } from '../bridge'

const maximized = ref(false)

onMounted(async () => {
  maximized.value = await api.win.isMaximized()
})

// ⚠ **最大化狀態要每次重新問。** 沒有「視窗被最大化了」這種通知，而使用者可以
//   雙擊標題列、拖到螢幕頂端、按 Win+↑——那些都不會經過這裡，自己記一個旗標
//   一定會和現實脫節。
const minimize = () => api.win.minimize()
const toggle = async () => {
  await api.win.toggleMaximize()
  maximized.value = await api.win.isMaximized()
}
const close = () => api.win.close()
</script>

<template>
  <!-- ⚠ 標題列整條是拖曳區，所以每個按得到的東西都要自己 .no-drag 退出來，
       否則點下去只會拖動視窗。 -->
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
 * ⚠ **這三顆刻意不跟著全站的圓角走，也不留內距。** 46px 寬、滿高、貼到最右邊，
 *   是 Windows 11 自己標題列的尺寸。理由不是「照抄慣例」而已：最大化時「關閉」
 *   落在螢幕角落，游標甩過去一定會停住（Fitts 定律，角落等於無限大的目標）。
 *   一旦加了圓角或內距，那個性質就沒了，換來的只是看起來整齊一點。
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
/* 關閉鍵的 hover 用紅底白字——這是 Windows 的慣例，換成別的只會讓人多想一秒 */
.ctl.close:hover {
  background: var(--red);
  color: #fff;
}
</style>
