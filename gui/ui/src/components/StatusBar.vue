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
      <!-- 執行中用呼吸燈號，其餘狀態用圖示。 -->
      <span v-if="tone === 'run'" class="nc-dot live" style="--glow: var(--green)"></span>
      <CircleX v-else-if="tone === 'bad'" :size="13" />
      <Loader v-else-if="tone === 'warn'" :size="13" class="icon-spin running" />
      <CircleCheck v-else :size="13" />
      <!-- 會一直變的值（副本評級）放這裡，不寫紀錄。 -->
      {{ host.fatal || host.status }}
    </span>

    <div class="flex-1"></div>

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
