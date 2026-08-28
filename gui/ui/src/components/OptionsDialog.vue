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

/** 改了但還沒寫回去的值：{ key: value }。 */
const draft = ref({})
const saving = ref(false)
const tab = ref('')

const groups = computed(() => host.options.groups)
const items = computed(() => host.options.items)
const dirty = computed(() => Object.keys(draft.value).length > 0)

// ⚠ **每次開啟都從後端的值重來。** 設定可能在這中間被人直接改過 config.yaml，
//   留著上一次的草稿只會把別人的改動蓋回去。
watch(
  () => props.show,
  (open) => {
    if (!open) return
    draft.value = {}
    // ⚠ **一定要指定第一個分頁。** `NTabs` 一旦被 `v-model` 控制住，值是空字串
    //   就等於「誰都沒選中」——畫面上分頁列在、內容區卻是空的。我為了讓標頭說明
    //   跟著分頁換而加上 v-model，就這樣把預設選取弄丟了（使用者一開就發現）。
    //   **把非受控元件改成受控時，記得自己補上原本由它決定的初始值。**
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
    強制回應是安全的：執行中那顆按鈕本來就停用，開得起來就代表沒有腳本在跑。
    ⚠ 對話框一定要有自己的不透明底色（`.opt-dialog`），否則在某些合成模式下底會
      畫不出來，變成看得到底下的內容。
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
      <!--
        ⚠ 分頁用**腳本**分，不靠鍵名前綴猜歸屬；分頁標題是後端讀腳本的 `name:`
          拿來的，和任務卡、紀錄同一個來源。前端不維護第二份對照表——維護兩份
          就會有不一致的那天。
      -->
      <NTabPane v-for="g in groups" :key="g.name" :name="g.name" :tab="g.title">
        <NScrollbar style="max-height: 52vh">
          <div class="pr-3 pt-1">
            <!--
              ⚠ **對齊靠 grid，不要靠 margin 猜。** 第一欄放核取方塊、第二欄放
                「標籤＋說明」，於是標籤和說明**天生**就對齊在同一條線上，
                而數值型（沒有方塊）的標籤也自動跟它們切齊。

                原本是給說明一個 `margin-left: 1.85em`——那是拿字級去推核取方塊的
                寬度，而說明的字級（12px）比標籤（14px）小，同樣的 em 換算出來
                **比較短**，所以說明反而跑到標籤左邊去。使用者一眼就看出來了：
                「下面說明還比較前面？」凡是「對齊到某個元件的內部尺寸」都不要用
                em／px 推算。
            -->
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

                  <!-- ⚠ 小數位是必要的：raid_plateau_players 預設 6.5，用整數欄位
                       會被無聲地寫回 6——使用者只是打開介面看一眼，門檻就被改掉了。 -->
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

                <!--
                  說明直接印在開關底下，不只掛 tooltip：使用者猶豫的正是「關掉會
                  怎樣」，那句話藏在滑鼠停留兩秒後才出現的地方等於沒寫。
                -->
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
/* 子項目往後縮一格。這是真的縮排，不是在標籤前面塞空白字元
   ——比例字型下補空白永遠對不齊，而且說明那一行也跟不上。 */
.opt.sub {
  padding-left: 28px;
}
/*
 * ⚠ **核取方塊要對齊「標籤那一行」，不是整塊的垂直中央。** 少了 `align-self: start`
 *   的話，這一格會被拉成整列的高度（標籤＋說明兩行），置中之後方塊就掉到兩行中間，
 *   看起來像沒對齊。min-height 要和 `.row` 一樣，兩邊才會落在同一條中線上。
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
