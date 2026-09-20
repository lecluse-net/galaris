<template>
  <q-select
    v-bind="$attrs"
    :model-value="modelValue"
    :options="filteredOptions"
    :label="label"
    :loading="loading"
    :error="loadFailed"
    :error-message="failureDetail"
    :disable="disable"
    :readonly="readonly"
    :clearable="clearable"
    emit-value
    map-options
    hide-bottom-space
    options-dense
    use-input
    input-debounce="300"
    @filter="filterOptions"
    @filter-abort="invalidate"
    @popup-hide="invalidate"
    @virtual-scroll="onVirtualScroll"
    @update:model-value="emitValue"
  >
    <template #prepend>
      <q-icon name="folder" style="color: var(--solaire-iris-accent)" />
    </template>
    <template v-if="canCreate || $slots.append" #append>
      <slot name="append" />
      <q-btn
        v-if="canCreate"
        flat
        round
        dense
        color="primary"
        icon="add"
        :aria-label="t('topic.createTitle')"
        @click.stop="createDialog = true"
      >
        <q-tooltip>{{ t('topic.createTitle') }}</q-tooltip>
      </q-btn>
    </template>
    <template #no-option>
      <q-item>
        <q-item-section class="text-grey">
          {{ t('topic.noOptions') }}
        </q-item-section>
      </q-item>
    </template>
  </q-select>
  <TopicFormDialog
    v-if="canCreate"
    :key="createFormKey"
    v-model="createDialog"
    @saved="selectCreatedTopic"
  />
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { apiErrorDetail, isCancelledRequest } from '@/core/api'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import TopicFormDialog from './TopicFormDialog.vue'
import { topicService } from '../services/topicService'
import type { Topic } from '../types'

interface TopicOption {
  label: string
  value: string
}

defineOptions({ inheritAttrs: false })

const props = withDefaults(defineProps<{
  modelValue: string | null
  label?: string
  disable?: boolean
  clearable?: boolean
  /** Enable creation in entry forms; leave disabled in filters. */
  allowCreate?: boolean
  readonly?: boolean
  excludeIds?: readonly string[]
}>(), {
  label: undefined,
  disable: false,
  clearable: true,
  allowCreate: false,
  readonly: false,
  excludeIds: () => [],
})

const emit = defineEmits<{
  'update:modelValue': [value: string | null]
}>()

const { t, locale } = useI18n()
const privilegeStore = usePrivilegeStore()
const canCreate = computed(() => props.allowCreate && !props.disable && !props.readonly
  && privilegeStore.hasPrivilege(privileges.TOPIC_EDIT)
  && privilegeStore.hasPrivilege(privileges.AGENT_MANAGE_ALL))
const createDialog = ref(false)
const createFormKey = ref(0)
const options = ref<TopicOption[]>([])
const filteredOptions = computed(() => options.value.filter(option => !props.excludeIds.includes(option.value)))
const loading = ref(false)
const loadFailed = ref(false)
const failureDetail = ref('')
const search = ref('')
let loadedCount = 0
let total = 0
let requestVersion = 0

function toOption(topic: Topic): TopicOption {
  return { label: topic.title.trim() || t('topic.unnamedBadge'), value: topic.id }
}

function sortOptions(items: TopicOption[]): TopicOption[] {
  return [...items].sort((left, right) => left.label.localeCompare(right.label, locale.value))
}

function addOption(option: TopicOption): void {
  if (options.value.some(item => item.value === option.value)) return
  options.value = sortOptions([...options.value, option])
}

function selectCreatedTopic(topic: Topic): void {
  if (!canCreate.value || !createDialog.value) return
  invalidate()
  loadFailed.value = false
  addOption(toOption(topic))
  emitValue(topic.id)
}

async function ensureSelectedTopic(topicId: string | null): Promise<void> {
  if (!topicId || options.value.some(item => item.value === topicId)) return
  const version = requestVersion
  try {
    const topic = await topicService.get(topicId)
    if (version === requestVersion && props.modelValue === topicId) addOption(toOption(topic))
  } catch {
    // A removed topic stays represented by its UUID until the parent refreshes.
    if (version === requestVersion && props.modelValue === topicId) addOption({ label: topicId, value: topicId })
  }
}

async function loadTopics(append = false): Promise<void> {
  const version = ++requestVersion
  loading.value = true
  loadFailed.value = false
  try {
    const page = await topicService.list({ skip: append ? loadedCount : 0, limit: 50, search: search.value })
    if (version !== requestVersion) return
    loadedCount = (append ? loadedCount : 0) + page.items.length
    total = page.total
    const previous = append ? options.value : []
    options.value = sortOptions([...new Map([...previous, ...page.items.map(toOption)].map(item => [item.value, item])).values()])
    await ensureSelectedTopic(props.modelValue)
  } catch (error) {
    if (version !== requestVersion || isCancelledRequest(error)) return
    loadFailed.value = true
    failureDetail.value = [t('topic.loadError'), apiErrorDetail(error)].filter(Boolean).join(' ')
    if (!append) {
      options.value = []
      loadedCount = 0
      total = 0
    }
    await ensureSelectedTopic(props.modelValue)
  } finally {
    if (version === requestVersion) loading.value = false
  }
}

function filterOptions(
  value: string,
  update: (callback: () => void) => void,
): void {
  search.value = value.trim()
  const pending = loadTopics()
  const version = requestVersion
  void pending.then(() => {
    if (version === requestVersion) update(() => {})
  })
}

function invalidate(): void {
  requestVersion += 1
  loading.value = false
}

function onVirtualScroll({ to }: { to: number }): void {
  if (!loading.value && loadedCount < total && to >= filteredOptions.value.length - 5) {
    void loadTopics(true)
  }
}

function emitValue(value: string | null): void {
  emit('update:modelValue', value || null)
}

watch(() => props.modelValue, value => { void ensureSelectedTopic(value) }, { immediate: true })
watch([() => props.modelValue, canCreate], () => { createDialog.value = false })
watch(createDialog, open => {
  // A cancelled save must not select a topic in a subsequently reopened form.
  if (!open) createFormKey.value += 1
})
onBeforeUnmount(invalidate)
</script>
