<template>
  <div class="q-gutter-y-sm">
    <template v-if="legacyModelId !== null">
      <q-input :model-value="t('nativeProcesses.legacyLlm', { id: legacyModelId })" outlined readonly
        :label="t('nativeProcesses.llmModel')" />
      <q-btn v-if="!readonly" outline color="primary" :label="t('nativeProcesses.useLlmProfiles')"
        @click="changeProfile()" />
    </template>
    <template v-else>
      <q-select :model-value="profileId('profile_id')" :options="primaryOptions" emit-value map-options outlined
        :readonly="readonly" :loading="loading" :label="t('nativeProcesses.primaryLlmProfile')"
        :error="error" :error-message="t('nativeProcesses.llmProfilesError')"
        @update:model-value="changeProfile('profile_id', $event)" />
      <q-select :model-value="profileId('fallback_profile_id')" :options="fallbackOptions" emit-value map-options outlined
        :readonly="readonly" :loading="loading" :label="t('nativeProcesses.fallbackLlmProfile')"
        @update:model-value="changeProfile('fallback_profile_id', $event)" />
      <q-select v-if="!decision" :model-value="modelField" :options="tierOptions" emit-value map-options outlined
        :readonly="readonly" :label="t('nativeProcesses.llmTextTier')" @update:model-value="changeProfile('model_field', $event)" />
      <q-btn v-if="error" outline color="primary" :label="t('nativeProcesses.retry')" @click="load" />
    </template>
    <div class="text-caption">{{ t(decision ? 'nativeProcesses.simpleLlmHint' : 'nativeProcesses.taskLlmHint') }}</div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { nativeProcessService, type ProcessProfileOptions } from '../services/nativeProcessService'

const props = defineProps<{ config: Record<string, unknown>; readonly: boolean; decision: boolean }>()
const emit = defineEmits<{ change: [key: string, value: unknown] }>()
const { t } = useI18n()
const catalogue = ref<ProcessProfileOptions | null>(null)
const loading = ref(false)
const error = ref(false)
let pending: AbortController | null = null

const tierFields = ['text_ultra_low_llm_id', 'text_low_llm_id', 'text_standard_llm_id', 'text_high_llm_id'] as const
const tierOptions = computed(() => tierFields.map(value => ({ value, label: t(`nativeProcesses.llmTextTiers.${value}`) })))
const legacyModelId = computed(() => typeof props.config.llm_id === 'number' ? props.config.llm_id : null)
const selection = computed(() => props.config.llm_profile as Record<string, unknown> | undefined)
const modelField = computed(() => props.decision ? 'decision_llm_id' : selection.value?.model_field ?? 'text_standard_llm_id')
function profileId(key: 'profile_id' | 'fallback_profile_id'): number | null {
  const id = selection.value?.[key]
  return typeof id === 'number' ? id : null
}
function profileLabel(id: number | null): string | undefined {
  return catalogue.value?.profiles.find(profile => profile.id === id)?.label
}
function options(defaultLabel: string, selected: number | null): { value: number | null; label: string }[] {
  return [{ value: null, label: defaultLabel },
    ...(catalogue.value?.profiles.map(profile => ({ value: profile.id, label: profile.label })) ?? []),
    ...(selected !== null && !profileLabel(selected) ? [{ value: selected, label: t('nativeProcesses.unavailableProfile', { id: selected }) }] : []),
  ]
}
const primaryOptions = computed(() => options(t('nativeProcesses.useCurrentLlmProfile', {
  profile: profileLabel(catalogue.value?.current_profile_id ?? null) ?? t('nativeProcesses.unknown'),
}), profileId('profile_id')))
const fallbackOptions = computed(() => {
  const label = profileLabel(catalogue.value?.default_fallback_profile_id ?? null)
  return options(label ? t('nativeProcesses.useDefaultFallbackLlmProfile', { profile: label }) : t('nativeProcesses.noFallbackLlmProfile'),
    profileId('fallback_profile_id'))
})

function changeProfile(key?: string, value?: unknown): void {
  if (props.readonly) return
  const profile: Record<string, unknown> = {
    model_field: modelField.value, profile_id: profileId('profile_id'), fallback_profile_id: profileId('fallback_profile_id'),
  }
  if (key) profile[key] = value
  emit('change', 'llm_profile', profile)
}

async function load(): Promise<void> {
  if (pending) return
  const request = new AbortController()
  pending = request
  loading.value = true
  error.value = false
  try {
    const result = await nativeProcessService.llmProfiles(request.signal)
    if (pending === request) catalogue.value = result
  } catch {
    if (pending === request) error.value = true
  } finally {
    if (pending === request) {
      pending = null
      loading.value = false
    }
  }
}

watch(legacyModelId, id => { if (id === null) void load() }, { immediate: true })
onBeforeUnmount(() => { pending?.abort(); pending = null })
</script>
