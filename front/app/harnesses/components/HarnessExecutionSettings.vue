<template>
  <section :aria-label="t('harnesses.policy.title')">
    <h2 class="text-h6 q-mt-none">{{ t('harnesses.policy.title') }}</h2>
    <div>
      <q-spinner v-if="loading" color="primary" />
      <q-banner v-else-if="failed" role="alert">
        {{ t('harnesses.policy.error') }}
        <template #action><q-btn flat :label="t('common.retry')" @click="load" /></template>
      </q-banner>
      <q-form v-else-if="selected && policy" @submit="save">
        <p>{{ t('harnesses.policy.hint') }}</p>
        <p v-if="providerCode">{{ t('harnesses.preferences.policyScope', { name: te(selected.label) ? t(selected.label) : selected.label }) }}</p>
        <q-select v-if="!providerCode" v-model="code" :options="options" emit-value map-options outlined
          :disable="saving" :label="t('harnesses.policy.provider')" />
        <div class="row q-col-gutter-md q-mt-sm">
          <div class="col-12 col-md-6">
            <q-select v-model="policy.disabled_capabilities" multiple use-chips emit-value map-options outlined
              :options="capabilityOptions" :disable="saving" :label="t('harnesses.policy.disabled')" />
          </div>
          <div v-for="field in fields" :key="field" class="col-12 col-md-6">
            <q-input v-model.number="policy[field]" type="number" outlined :disable="saving"
              :step="isSize(field) ? 0.000001 : 'any'"
              :label="t(`harnesses.policy.${field}`)" :hint="isOptional(field) ? t('harnesses.policy.optional') : undefined" />
          </div>
        </div>
        <p v-if="saveFailed" class="q-mt-md" role="alert">{{ t('harnesses.policy.saveError') }}</p>
        <p v-if="saved" class="q-mt-md" role="status">{{ t('harnesses.policy.saved') }}</p>
        <q-btn class="q-mt-md" type="submit" color="primary" :loading="saving" :label="t('common.save')" />
      </q-form>
    </div>
      <q-banner v-if="!loading && !failed && !availableConfigurations.length">{{ t('harnesses.preferences.noPolicies') }}</q-banner>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { sizeInMegabytes, sizeFromMegabytes } from '@/core/util'
import { harnessService, type HarnessExecutionConfiguration, type HarnessExecutionPolicy } from '../services/harnessService'

const { providerCode } = defineProps<{
  providerCode?: string
}>()
const { t, te } = useI18n()
const configurations = ref<HarnessExecutionConfiguration[]>([])
const code = ref('')
const loading = ref(false)
const saving = ref(false)
const failed = ref(false)
const saveFailed = ref(false)
const saved = ref(false)
const policy = ref<HarnessExecutionPolicy | null>(null)
let generation = 0
const availableConfigurations = computed(() => configurations.value.filter(item => (
  !providerCode || item.provider_code === providerCode
)))
const selected = computed(() => availableConfigurations.value.find(item => item.provider_code === code.value))
const options = computed(() => availableConfigurations.value.map(item => ({
  value: item.provider_code, label: te(item.label) ? t(item.label) : item.label,
})))
const capabilityOptions = computed(() => (selected.value?.descriptor.configurable ?? []).map(value => ({
  value, label: t(`harnesses.policy.capabilities.${value}`),
})))
const optionalFields = ['max_parallel_tasks', 'execution_timeout_seconds', 'idle_timeout_seconds'] as const
const sizeFields = ['max_message_bytes', 'max_result_bytes', 'max_stream_bytes'] as const
const fields = [...optionalFields, 'stream_close_timeout_seconds', ...sizeFields] as const
const isOptional = (field: string): boolean => (optionalFields as readonly string[]).includes(field)
const isSize = (field: string): boolean => (sizeFields as readonly string[]).includes(field)

function displayPolicy(value: HarnessExecutionPolicy): HarnessExecutionPolicy {
  const result = { ...value, disabled_capabilities: [...value.disabled_capabilities] }
  for (const field of sizeFields) result[field] = sizeInMegabytes(value[field])
  return result
}

watch(selected, value => {
  policy.value = value ? displayPolicy(value.descriptor.policy) : null
  saved.value = false
  saveFailed.value = false
})

async function load(): Promise<void> {
  if (loading.value || configurations.value.length) return
  const ticket = ++generation
  loading.value = true
  failed.value = false
  try {
    const result = await harnessService.executionConfigurations()
    if (ticket !== generation) return
    configurations.value = result.data
    code.value = availableConfigurations.value[0]?.provider_code ?? ''
  } catch {
    if (ticket === generation) failed.value = true
  } finally {
    if (ticket === generation) loading.value = false
  }
}

async function save(): Promise<void> {
  if (!selected.value || !policy.value) return
  const ticket = generation
  const current = selected.value
  const update = { ...policy.value }
  for (const field of sizeFields) update[field] = sizeFromMegabytes(update[field])
  for (const field of optionalFields) {
    if (update[field] === null || String(update[field]) === '') update[field] = null
  }
  saving.value = true
  saveFailed.value = false
  saved.value = false
  try {
    const result = await harnessService.saveExecutionConfiguration(current.provider_code, current.revision, update)
    if (ticket !== generation) return
    configurations.value = configurations.value.map(item => item.provider_code === current.provider_code ? result.data : item)
    // The selection watcher clears feedback while replacing its snapshot.
    policy.value = displayPolicy(result.data.descriptor.policy)
    await nextTick()
    if (ticket !== generation) return
    saved.value = true
  } catch {
    if (ticket === generation) saveFailed.value = true
  } finally {
    if (ticket === generation) saving.value = false
  }
}

onBeforeUnmount(() => { generation += 1 })
onMounted(load)
</script>
