<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { NButton, NModal, useMessage } from 'naive-ui'
import { FileCog, FolderOpen, RotateCcw } from 'lucide-vue-next'
import { useHostStore } from '../stores/host'

const props = defineProps({ show: Boolean })
const emit = defineEmits(['update:show'])

const host = useHostStore()
const message = useMessage()

const text = ref('')
const original = ref('')
const path = ref('')
const error = ref('')
const loading = ref(false)
const saving = ref(false)
const ta = ref(null)
const gutter = ref(null)

const dirty = computed(() => text.value !== original.value)
const lines = computed(() => text.value.split('\n').length)

// ⚠ **每次開啟都重讀。** 設定檔可能在這中間被介面上的開關、或使用者自己用編輯器
//   改過；留著上一次的草稿等於拿一份過期的全文去覆蓋別人的改動。
watch(
  () => props.show,
  async (open) => {
    if (!open) return
    error.value = ''
    loading.value = true
    try {
      const r = await host.call('config_read')
      text.value = original.value = r.text
      path.value = r.path
    } catch (e) {
      message.error(e.message)
      emit('update:show', false)
    } finally {
      loading.value = false
    }
  }
)

async function save() {
  saving.value = true
  error.value = ''
  try {
    await host.call('config_write', { text: text.value })
    original.value = text.value
    await host.refresh()
    message.success('已寫回 config.yaml')
    emit('update:show', false)
  } catch (e) {
    // ⚠ 這一則要留在畫面上，不能用 message——它是**多行**的（PyYAML 會指出行號
    //   與欄位），而 message 只有一行、幾秒後還會自己消失。
    error.value = e.message
  } finally {
    saving.value = false
  }
}

function revert() {
  text.value = original.value
  error.value = ''
}

function close() {
  if (dirty.value) {
    message.warning('有改動還沒儲存，按「儲存」才會寫回設定檔')
    return
  }
  emit('update:show', false)
}

/**
 * Tab 打兩個空白。
 *
 * ⚠ **YAML 不吃 tab 字元**（規格就是禁止用 tab 縮排），而瀏覽器的 Tab 預設是
 *   把焦點移到下一個元件——兩種行為都不是使用者要的。
 */
function onTab(e) {
  e.preventDefault()
  const el = e.target
  const { selectionStart: a, selectionEnd: b } = el
  text.value = text.value.slice(0, a) + '  ' + text.value.slice(b)
  nextTick(() => {
    el.selectionStart = el.selectionEnd = a + 2
  })
}

/** 行號要跟著內文捲。 */
function onScroll(e) {
  if (gutter.value) gutter.value.scrollTop = e.target.scrollTop
}
</script>

<template>
  <NModal
    :show="show"
    preset="card"
    class="cfg-dialog"
    style="width: 860px; max-width: 94vw"
    title="編輯設定檔"
    :mask-closable="!dirty"
    @update:show="(v) => (v ? emit('update:show', true) : close())"
  >
    <!--
      ⚠ **這裡編的是整份原文，包含介面上沒有的那些欄位**（`adb`、`runtime`、
        腳本清單）。註解就是使用者的說明書，所以是「原文進、原文出」——不經過
        YAML 的 dump 往返，那一趟會把註解全部洗掉。
    -->
    <div class="hero">
      <span class="ic"><FileCog :size="20" /></span>
      <div>
        <div class="sub">
          存檔前會用真正的載入流程驗一次，驗不過就整份不寫入，所以改壞了不會等到
          下一次啟動才發現。註解與排版原樣保留。
        </div>
        <div class="path selectable">{{ path }}</div>
      </div>
    </div>

    <div class="editor">
      <div ref="gutter" class="gutter">
        <div v-for="n in lines" :key="n">{{ n }}</div>
      </div>
      <textarea
        ref="ta"
        v-model="text"
        spellcheck="false"
        :disabled="loading || saving"
        @keydown.tab="onTab"
        @scroll="onScroll"
      ></textarea>
    </div>

    <div v-if="error" class="err">{{ error }}</div>

    <template #footer>
      <div class="flex items-center gap-2">
        <span style="font-size: 12px; color: var(--text-2)">{{ lines }} 行</span>
        <span v-if="dirty" style="font-size: 12px; color: var(--amber)">尚未儲存</span>
        <div class="flex-1"></div>
        <NButton size="small" :disabled="!dirty || saving" @click="revert">
          <template #icon><RotateCcw :size="14" /></template>
          還原
        </NButton>
        <NButton size="small" @click="host.reveal('config')">
          <template #icon><FolderOpen :size="14" /></template>
          用系統編輯器開啟
        </NButton>
        <NButton size="small" @click="emit('update:show', false)">關閉</NButton>
        <NButton size="small" type="primary" :disabled="!dirty" :loading="saving" @click="save">
          儲存
        </NButton>
      </div>
    </template>
  </NModal>
</template>

<style scoped>
.hero {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  margin-bottom: 12px;
}
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
.sub {
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--text-2);
}
.path {
  margin-top: 2px;
  font-size: 12px;
  color: var(--text-2);
  opacity: 0.85;
  word-break: break-all;
}

/*
 * ⚠ **設定檔一定要用等寬字型顯示。** YAML 的意思全在縮排上，比例字型下兩個空白
 *   和一個全形字看起來一樣寬，改縮排等於在猜。
 */
.editor {
  display: flex;
  height: 52vh;
  min-height: 260px;
  border: 1px solid var(--border);
  border-radius: var(--radius-input);
  background: var(--bg-0);
  overflow: hidden;
  font-family: Consolas, 'Cascadia Mono', 'Courier New', monospace;
  font-size: 13px;
  line-height: 1.55;
}
.gutter {
  flex: none;
  width: 46px;
  padding: 10px 8px 10px 0;
  text-align: right;
  color: var(--text-2);
  background: var(--bg-1);
  border-right: 1px solid var(--border-soft);
  overflow: hidden;
  user-select: none;
}
textarea {
  flex: 1;
  min-width: 0;
  padding: 10px 12px;
  border: 0;
  outline: none;
  resize: none;
  background: transparent;
  color: var(--text-0);
  font: inherit;
  white-space: pre;
  overflow: auto;
  tab-size: 2;
}

/* 驗證失敗的訊息是多行的（PyYAML 會指出行號），所以照原樣排 */
.err {
  margin-top: 10px;
  padding: 9px 11px;
  border: 1px solid color-mix(in srgb, var(--red) 45%, transparent);
  border-radius: var(--radius-input);
  background: color-mix(in srgb, var(--red) 12%, transparent);
  color: var(--red);
  font-size: 12.5px;
  line-height: 1.6;
  white-space: pre-wrap;
  max-height: 120px;
  overflow: auto;
}
</style>
