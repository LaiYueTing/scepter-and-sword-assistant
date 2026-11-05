<script setup>
import { computed } from 'vue'
import { NButton, NModal, useMessage } from 'naive-ui'
import { ExternalLink, FolderOpen, Info } from 'lucide-vue-next'
import { useHostStore } from '../stores/host'
import { api } from '../bridge'

defineProps({ show: { type: Boolean, default: false } })
defineEmits(['update:show'])

const host = useHostStore()
const message = useMessage()

const REPO = 'https://github.com/LaiYueTing/scepter-and-sword-assistant'

/**
 * 更新狀態的文字。⚠「還沒檢查」與「已經是最新」要分開。
 */
const updateText = computed(() => {
  const u = host.update
  if (!u) return '尚未檢查'
  if (!u.found) return '已經是最新版'
  return `有新版 v${u.version}` + (u.can_apply ? '（可直接更新）' : `（${u.why || '這個環境不能自動更新'}）`)
})

async function check() {
  try {
    await host.checkUpdate(false)
    message.info('正在檢查更新 ⋯')
  } catch (e) {
    message.error(e.message)
  }
}
</script>

<template>
  <NModal
    :show="show"
    preset="card"
    title="關於"
    style="width: 560px"
    :bordered="false"
    @update:show="(v) => $emit('update:show', v)"
  >
    <!-- 版本、執行方式、設定檔與日誌的路徑，回報問題時使用。標題底下不放介紹。 -->
    <div class="hero">
      <span class="ic"><Info :size="20" /></span>
      <div class="nm">杖劍傳說助手</div>
    </div>

    <!-- 內容要可以選取複製。 -->
    <dl class="kv selectable">
      <dt>版本</dt>
      <dd>v{{ host.version || '—' }}</dd>

      <dt>更新狀態</dt>
      <dd class="row">
        <span>{{ updateText }}</span>
        <NButton size="tiny" :disabled="host.running || host.closing" @click="check">
          檢查更新
        </NButton>
      </dd>

      <dt>執行方式</dt>
      <dd>{{ host.frozen ? '打包的單一執行檔' : '從原始碼執行（Python）' }}</dd>

      <dt>設定檔</dt>
      <dd class="row">
        <span class="path">{{ host.configPath || '—' }}</span>
        <NButton size="tiny" @click="host.reveal('config')">
          <template #icon><FolderOpen :size="13" /></template>
          開啟
        </NButton>
      </dd>

      <dt>日誌資料夾</dt>
      <dd class="row">
        <span class="path">{{ host.logDir || '—' }}</span>
        <NButton size="tiny" @click="host.reveal('logs')">
          <template #icon><FolderOpen :size="13" /></template>
          開啟
        </NButton>
      </dd>

      <dt>專案位置</dt>
      <dd class="row">
        <span class="path">{{ REPO }}</span>
        <NButton size="tiny" @click="api.app.openExternal(REPO)">
          <template #icon><ExternalLink :size="13" /></template>
          開啟
        </NButton>
      </dd>
    </dl>
  </NModal>
</template>

<style scoped>
.hero {
  display: flex;
  gap: 12px;
  align-items: center;
  margin-bottom: 16px;
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
.nm {
  font-weight: 600;
  font-size: 15px;
}

/*
 * 欄位名與值用 grid 分兩欄（比例字型，不用補空白對齊）。
 */
.kv {
  display: grid;
  grid-template-columns: auto 1fr;
  column-gap: 16px;
  row-gap: 9px;
  margin: 0;
  align-items: center;
}
dt {
  color: var(--text-1);
  font-size: 13px;
  white-space: nowrap;
}
dd {
  margin: 0;
  min-width: 0;
  font-size: 13px;
}
.row {
  display: flex;
  align-items: center;
  gap: 8px;
}
/* 路徑過長時截斷 */
.path {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-2);
  font-size: 12.5px;
}
</style>
