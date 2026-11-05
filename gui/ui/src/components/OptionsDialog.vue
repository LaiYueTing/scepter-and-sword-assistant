<script setup>
import { computed, ref, watch } from 'vue'
import {
  NButton,
  NCheckbox,
  NInputNumber,
  NModal,
  NScrollbar,
  NTabPane,
  NTabs,
  useMessage
} from 'naive-ui'
import { useHostStore } from '../stores/host'

const props = defineProps({ show: Boolean })
const emit = defineEmits(['update:show'])

const host = useHostStore()
const message = useMessage()

/** 修改後還沒寫回的值：{ key: value }。 */
const draft = ref({})
const saving = ref(false)
const tab = ref('')

const groups = computed(() => host.options.groups)
const items = computed(() => host.options.items)
const dirty = computed(() => Object.keys(draft.value).length > 0)

// ⚠ 每次開啟都從後端的值重來，不保留草稿。
watch(
  () => props.show,
  (open) => {
    if (!open) return
    draft.value = {}
    // ⚠ 要指定第一個分頁：`NTabs` 受 `v-model` 控制時，空字串表示沒有選中。
    tab.value = groups.value[0]?.name || ''
  }
)

function valueOf(key) {
  return key in draft.value ? draft.value[key] : items.value[key]?.value
}

function set(key, value) {
  if (items.value[key]?.value === value) delete draft.value[key]
  else draft.value[key] = value
  draft.value = { ...draft.value }
}

function toggle(key) {
  set(key, !valueOf(key))
}

async function save() {
  saving.value = true
  try {
    await host.save(
      Object.entries(draft.value).map(([key, value]) => ({
        path: ['options', key],
        value
      }))
    )
    draft.value = {}
    message.success('已寫回 config.yaml')
    emit('update:show', false)
  } catch (e) {
    message.error(e.message)
  } finally {
    saving.value = false
  }
}

function close() {
  if (dirty.value) {
    message.warning('有改動還沒儲存，按「儲存」才會寫回設定檔')
    return
  }
  emit('update:show', false)
}
</script>

<template>
  <!--
    強制回應：開得起來就代表沒有腳本在跑。
    ⚠ `.opt-dialog` 要有不透明底色。
  -->
  <NModal
    :show="show"
    :mask-closable="!dirty"
    preset="card"
    class="opt-dialog"
    style="width: 720px; max-width: 92vw"
    title="玩法設定"
    @update:show="(v) => (v ? emit('update:show', true) : close())"
  >
    <NTabs v-model:value="tab" type="line" animated>
      <!-- 分頁依腳本分，標題來自腳本的 `name:`。 -->
      <NTabPane v-for="g in groups" :key="g.name" :name="g.name" :tab="g.title">
        <NScrollbar style="max-height: 52vh">
          <div class="pr-3 pt-1">
            <!-- 第一欄放核取方塊，第二欄放標籤與說明，對齊靠 grid。 -->
            <div v-for="key in g.keys" :key="key" class="opt" :class="{ sub: items[key].sub }">
              <div class="box">
                <NCheckbox
                  v-if="items[key].kind === 'bool'"
                  :checked="valueOf(key)"
                  @update:checked="(v) => set(key, v)"
                />
              </div>

              <div class="body">
                <div class="row">
                  <span
                    class="lab"
                    :class="{ clickable: items[key].kind === 'bool' }"
                    @click="items[key].kind === 'bool' && toggle(key)"
                  >
                    {{ items[key].label }}
                  </span>

                  <!-- ⚠ 小數位不可省略：raid_plateau_players 預設 6.5。 -->
                  <NInputNumber
                    v-if="items[key].kind === 'number'"
                    :value="valueOf(key)"
                    :min="items[key].min"
                    :max="items[key].max"
                    :step="items[key].step"
                    :precision="items[key].decimals"
                    size="small"
                    style="width: 108px; flex: none"
                    @update:value="(v) => set(key, v ?? items[key].min)"
                  />
                </div>

                <!-- 說明直接印在開關底下。 -->
                <div v-if="items[key].hint" class="hint">{{ items[key].hint }}</div>
              </div>
            </div>
          </div>
        </NScrollbar>
      </NTabPane>

    </NTabs>

    <template #footer>
      <div class="flex items-center gap-2">
        <span v-if="dirty" style="font-size: 12px; color: var(--amber)">
          有 {{ Object.keys(draft).length }} 項改動還沒儲存
        </span>
        <div class="flex-1"></div>
        <NButton :disabled="saving" @click="emit('update:show', false)">取消</NButton>
        <NButton type="primary" :disabled="!dirty" :loading="saving" @click="save">
          儲存
        </NButton>
      </div>
    </template>
  </NModal>
</template>

<style scoped>
.opt {
  display: grid;
  grid-template-columns: 18px 1fr;
  column-gap: 10px;
  padding: 7px 0;
}
.opt + .opt {
  border-top: 1px solid var(--border-soft);
}
/* 子項目縮排 */
.opt.sub {
  padding-left: 28px;
}
/*
 * ⚠ 核取方塊對齊標籤那一行：`align-self: start`，min-height 與 `.row` 相同。
 */
.box {
  display: flex;
  align-items: center;
  align-self: start;
  min-height: 22px;
}
.row {
  display: flex;
  align-items: center;
  gap: 12px;
  min-height: 22px;
}
.lab {
  flex: 1;
  color: var(--text-0);
  line-height: 1.5;
}
.lab.clickable {
  cursor: pointer;
}
.hint {
  margin-top: 2px;
  font-size: 12.5px;
  line-height: 1.6;
  color: var(--text-2);
}
</style>
