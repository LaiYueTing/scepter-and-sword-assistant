<script setup>
import LogView from '../components/LogView.vue'
</script>

<template>
  <!-- 只看紀錄的全螢幕版。儀表板上那塊只有一半寬，往回翻長訊息時不夠看。 -->
  <div class="p-3.5 h-full" style="min-height: 0">
    <LogView class="h-full" />
  </div>
</template>
