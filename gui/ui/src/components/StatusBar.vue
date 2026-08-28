<script setup>
import { computed } from 'vue'
import { CircleCheck, CircleX, Loader } from 'lucide-vue-next'
import { useHostStore } from '../stores/host'

const host = useHostStore()

const tone = computed(() => {
  if (host.fatal) return 'bad'
  if (host.closing) return 'warn'
  if (host.running) return 'run'
  return 'idle'
})
</script>

<template>
  <footer
    class="app-chrome app-chrome--bottom flex items-center gap-2 px-3 border-t"
    style="height: 28px; font-size: 12.5px"
  >
    <span class="flex items-center gap-1.5" :class="tone">
      <!--
        ⚠ **執行中用會呼吸的燈號，不要再配一顆圖示。** 兩個都放的話是同一件事講兩次，
          而狀態列只有 28px 高。其餘狀態是「一次性的結果」（壞了／收尾中／閒著），
          圖示的形狀本身就說得完，不需要一直發光去搶注意力。
      -->
      <span v-if="tone === 'run'" class="nc-dot live" style="--glow: var(--green)"></span>
      <CircleX v-else-if="tone === 'bad'" :size="13" />
      <Loader v-else-if="tone === 'warn'" :size="13" class="icon-spin running" />
      <CircleCheck v-else :size="13" />
      <!-- 狀態列放「會一直變的值」——副本戰鬥中的評級每輪都在動，寫進紀錄只會洗版 -->
      {{ host.fatal || host.status }}
    </span>

    <div class="flex-1"></div>

    <!--
      ⚠ **右邊刻意留白。** 這裡原本一直掛著 config.yaml 的完整路徑，而那是一個
        **不會變**的值——常駐佔著一整條，卻只在「要抄路徑」那一刻有用，而那一刻
        現在有「關於」可以開（那裡還能直接選取複製）。狀態列的位置留給會變的東西。
    -->
  </footer>
</template>

<style scoped>
.bad {
  color: var(--red);
}
.warn {
  color: var(--amber);
}
.run {
  color: var(--green);
}
.idle {
  color: var(--text-1);
}
</style>
