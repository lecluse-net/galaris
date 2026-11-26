<template>
  <q-card flat :bordered="!embedded" :class="{ 'personal-llm-profile': !embedded }">
    <q-card-section :class="embedded ? 'q-pa-none' : 'q-pb-sm'">
      <div :class="embedded ? 'text-subtitle2 q-mb-xs' : 'text-h6'">
        <q-icon v-if="!embedded" name="model_training" color="primary" size="sm" class="q-mr-sm" />{{ t('personalVoice.models') }}
      </div>
    </q-card-section>
    <component :is="embedded ? 'div' : QForm" :aria-label="t('personalVoice.models')"
      :class="{ 'q-pa-md': !embedded }" @submit.prevent="save">
      <q-linear-progress v-if="loading" indeterminate />
      <q-banner v-if="!embedded" dense rounded class="q-mb-sm">{{ t('personalVoice.modelsIntro') }}</q-banner>
      <div class="personal-llm-fields">
        <q-select v-model="values.profile_id" :options="profileOptions" dense outlined emit-value map-options
          :disable="!loaded || saving || disabled" :label="t('personalVoice.profile')"
          :hint="embedded ? undefined : t('personalVoice.profileHint')" />
        <q-select v-model="voiceSelection" :options="voiceOptions" dense outlined emit-value map-options
          :disable="!loaded || saving || disabled" :label="t('personalVoice.voiceTitle')"
          :hint="embedded ? undefined : t(values.voice_mode === 'realtime' ? 'personalVoice.nativeHint' : 'personalVoice.ttsHint')">
          <template #option="{ itemProps, opt }">
            <q-item v-if="opt.group" dense>
              <q-item-section><q-item-label header class="text-weight-bold text-primary">{{ opt.label }}</q-item-label></q-item-section>
            </q-item>
            <q-item v-else v-bind="itemProps">
              <q-item-section avatar><q-icon :name="opt.icon" color="primary" /></q-item-section>
              <q-item-section>
                <q-item-label>{{ opt.label }}</q-item-label>
                <q-item-label v-if="opt.caption" caption>{{ opt.caption }}</q-item-label>
              </q-item-section>
            </q-item>
          </template>
        </q-select>
      </div>
      <div v-if="options.native_voices_error" role="status">{{ t('personalVoice.nativeCatalogError') }}</div>
      <div v-if="error" role="alert">{{ error }}</div>
      <div v-if="saved" role="status">{{ t('personalVoice.saved') }}</div>
      <div v-if="!embedded || (!loaded && !loading)" class="row justify-end q-gutter-sm q-mt-sm">
        <q-btn v-if="!loaded && !loading" outline color="primary" :label="t('personalVoice.retry')" @click="load" />
        <q-btn v-if="!embedded" type="submit" color="primary" :label="t('personalVoice.save')" :loading="saving" :disable="!loaded" />
      </div>
    </component>
  </q-card>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { QForm } from 'quasar'
import service, { type PersonalLlmOptions, type PersonalLlmPreferences } from '../services/personalLlmService'

const props = defineProps<{ userId?: number; embedded?: boolean; disabled?: boolean }>()
const emit = defineEmits<{ draft: [value: PersonalLlmPreferences | null] }>()
const { t } = useI18n()
const values = ref<PersonalLlmPreferences>({ profile_id: null, voice_llm_id: null, voice_mode: 'tts', voice_code: null })
let initial: PersonalLlmPreferences = { ...values.value }
const options = ref<PersonalLlmOptions>({ profiles: [], current_profile_id: null, voices: [], native_voices: [] })
const loading = ref(false), loaded = ref(false), saving = ref(false), saved = ref(false), error = ref('')
let generation = 0

const profileOptions = computed(() => [{
  label: t('personalVoice.currentProfile', {
    profile: options.value.profiles.find(profile => profile.id === options.value.current_profile_id)?.label ?? t('personalVoice.notConfigured'),
  }), value: null,
}, ...options.value.profiles.map(profile => ({ label: profile.label, value: profile.id }))])

const voiceSelection = computed({
  get: () => values.value.voice_llm_id === null ? 'none'
    : values.value.voice_mode === 'tts' ? `tts:${values.value.voice_llm_id}`
      : `realtime:${values.value.voice_llm_id}:${encodeURIComponent(values.value.voice_code ?? '')}`,
  set: (value: string) => {
    const [mode, id, code] = value.split(':')
    values.value.voice_llm_id = value === 'none' ? null : Number(id)
    values.value.voice_mode = mode === 'realtime' ? 'realtime' : 'tts'
    values.value.voice_code = mode === 'realtime' ? decodeURIComponent(code) : null
  },
})
const voiceOptions = computed(() => [
  { label: t('personalVoice.ttsGroup'), value: 'group:tts', group: true, disable: true },
  { label: t('personalVoice.noVoice'), value: 'none', icon: 'volume_off' },
  ...options.value.voices.map(voice => ({ label: voice.label, value: `tts:${voice.id}`, icon: 'record_voice_over' })),
  { label: t('personalVoice.nativeGroup'), value: 'group:native', group: true, disable: true },
  ...options.value.native_voices.map(voice => ({
    label: voice.label, caption: voice.caption, icon: 'spatial_audio',
    value: `realtime:${voice.model_id}:${encodeURIComponent(voice.voice_code)}`,
  })),
  ...(options.value.native_voices.length ? [] : [{ label: t('personalVoice.noNativeVoice'), value: 'unavailable', disable: true, icon: 'info' }]),
])

async function load(): Promise<void> {
  const current = ++generation
  if (props.embedded) emit('draft', null)
  loading.value = true; loaded.value = false; saving.value = false; error.value = ''; saved.value = false
  try {
    const [preferences, catalog] = await Promise.all([
      props.embedded && props.userId === undefined
        ? { profile_id: null, voice_llm_id: null, voice_mode: 'tts' as const, voice_code: null }
        : service.preferences(props.userId),
      service.options(),
    ])
    if (current !== generation) return
    initial = { ...preferences }
    values.value = preferences; options.value = catalog; loaded.value = true
  } catch { if (current === generation) error.value = t('personalVoice.settingsError') }
  finally { if (current === generation) loading.value = false }
}
async function save(): Promise<void> {
  if (!loaded.value || saving.value) return
  const current = generation
  saving.value = true; error.value = ''; saved.value = false
  try { await service.save({ ...values.value }, props.userId); if (current === generation) saved.value = true }
  catch { if (current === generation) error.value = t('personalVoice.settingsError') }
  finally { if (current === generation) saving.value = false }
}
watch(() => props.userId, load, { immediate: true })
watch(values, value => {
  saved.value = false
  if (props.embedded && loaded.value) {
    const changed = value.profile_id !== initial.profile_id || value.voice_llm_id !== initial.voice_llm_id
      || value.voice_mode !== initial.voice_mode || value.voice_code !== initial.voice_code
    emit('draft', changed ? { ...value } : null)
  }
}, { deep: true })
onBeforeUnmount(() => { generation += 1 })
</script>

<style scoped>
.personal-llm-fields {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}
@media (max-width: 1023px) {
  .personal-llm-profile .personal-llm-fields { grid-template-columns: 1fr; }
}
</style>
