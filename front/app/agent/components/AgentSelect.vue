<template>
  <q-select
    :model-value="selectedOption?.value ?? null"
    :options="allowedOptions"
    :label="label"
    :stack-label="Boolean(label)"
    emit-value
    map-options
    hide-bottom-space
    v-bind="$attrs"
    :loading="loading || Boolean($attrs.loading)"
    :error="failed || Boolean($attrs.error)"
    :error-message="failed ? failureDetail : typeof $attrs['error-message'] === 'string' ? $attrs['error-message'] : undefined"
    @update:model-value="select"
    @popup-show="open"
    @popup-hide="close"
    :aria-label="typeof $attrs['aria-label'] === 'string' ? $attrs['aria-label'] : label"
  >
    <template #no-option>
      <q-item>
        <q-item-section>
          <q-btn v-if="failed" flat :label="t('common.retry')" @click="refresh" />
          <span v-else>{{ t('agent.noAgent') }}</span>
        </q-item-section>
      </q-item>
    </template>
    <template v-if="$slots.prepend" #prepend>
      <slot name="prepend" />
    </template>

    <template #selected>
      <div v-if="selectedOption" class="row items-center no-wrap q-gutter-sm">
        <slot v-if="selectedOption.value !== null" name="avatar" :option="selectedOption" size="28px">
          <AgentAvatar
            :agent-id="selectedOption.value"
            :name="selectedOption.label"
            :has-avatar="selectedOption.hasAvatar"
            size="28px"
          />
        </slot>
        <span class="ellipsis">{{ selectedOption.label }}</span>
      </div>
      <span v-else class="text-grey-7">{{ t('agent.selectPlaceholder') }}</span>
    </template>

    <template #option="scope">
      <q-item v-bind="scope.itemProps" :aria-label="scope.opt.label">
        <q-item-section v-if="scope.opt.value !== null" avatar>
          <slot name="avatar" :option="scope.opt" size="32px">
            <AgentAvatar
              :agent-id="scope.opt.value"
              :name="scope.opt.label"
              :has-avatar="scope.opt.hasAvatar"
              size="32px"
            />
          </slot>
        </q-item-section>
        <q-item-section>
          <q-item-label>{{ scope.opt.label }}</q-item-label>
          <q-item-label v-if="scope.opt.caption" caption>
            {{ scope.opt.caption }}
          </q-item-label>
        </q-item-section>
      </q-item>
    </template>
  </q-select>
</template>

<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { isAxiosError } from 'axios'
import AgentAvatar from './AgentAvatar.vue'
import { useAgentStore } from '../stores/agentStore'
import { AUTH_TOKEN_CHANGED_EVENT, apiErrorDetail, isCancelledRequest } from '@/core/api'
import { usePrivilegeStore } from '@/core/authorize'
import { getAgentSelection, type AgentSelectionScope, type AgentSelectionOption as AuthorizedAgent } from '../services/agentSelectionService'

defineOptions({ inheritAttrs: false })

interface AgentSelectOption {
  label: string
  value: number | null
  caption?: string
  disable?: boolean
  hasAvatar?: boolean
}

const { options, label, loadAgents = true, scope = 'management' } = defineProps<{
  options: readonly AgentSelectOption[]
  label?: string
  loadAgents?: boolean
  scope?: AgentSelectionScope
}>()
const model = defineModel<number | null>({ required: true })
const agentStore = useAgentStore()
const privileges = usePrivilegeStore()
const authorized = ref<AuthorizedAgent[]>([])
const loading = ref(false)
const failed = ref(false)
const failureDetail = ref('')
let request = 0
let popupOpen = false
const { t } = useI18n()
const allowedIds = computed(() => new Set(authorized.value.map(agent => agent.id)))
const allowedOptions = computed(() => options.filter(option => option.value === null || allowedIds.value.has(option.value)))
const selectedOption = computed(
  () => allowedOptions.value.find(option => option.value === model.value) ?? null,
)

function select(value: number | null): void {
  if (value === null || allowedOptions.value.some(option => option.value === value && !option.disable)) {
    model.value = value
  }
}

async function refresh(): Promise<void> {
  const current = ++request
  loading.value = true
  failed.value = false
  try {
    const result = await getAgentSelection(scope)
    if (current !== request) return
    if (loadAgents && scope === 'management' && agentStore.agents.length === 0) {
      await agentStore.fetchAgents()
      if (current !== request) return
      if (agentStore.error) throw agentStore.error
    }
    authorized.value = result
    if (model.value !== null && !allowedIds.value.has(model.value)) model.value = null
  } catch (error) {
    if (current !== request || isCancelledRequest(error)) return
    authorized.value = []
    failed.value = true
    failureDetail.value = [t('agent.selectionLoadError'), apiErrorDetail(error)].filter(Boolean).join(' ')
    // A transport failure does not revoke the user's choice. Keep it for recovery;
    // the empty authorized list still prevents choosing an unverified agent.
    if (isAxiosError(error) && [401, 403].includes(error.response?.status ?? 0)) model.value = null
  } finally {
    if (current === request) loading.value = false
  }
}

function invalidate(): void {
  request += 1
  authorized.value = []
  failed.value = false
  loading.value = false
  if (popupOpen || model.value !== null) void refresh()
}
function open(): void {
  popupOpen = true
  void refresh()
}
function close(): void {
  popupOpen = false
  request += 1
  loading.value = false
}
watch(() => [scope, privileges.privileges], invalidate, { immediate: true, deep: true })
watch(model, value => {
  if (value !== null && !allowedIds.value.has(value) && !loading.value) void refresh()
})
onBeforeUnmount(() => {
  request += 1
  window.removeEventListener(AUTH_TOKEN_CHANGED_EVENT, invalidate)
})

onMounted(() => {
  window.addEventListener(AUTH_TOKEN_CHANGED_EVENT, invalidate)
})
</script>
