<template>
  <q-card flat bordered :class="{ 'personal-llm-settings--compact': userId === undefined }">
    <q-card-section class="row items-center q-gutter-sm">
      <q-icon name="model_training" color="primary" size="sm" />
      <div class="text-h6">{{ t('personalVoice.models') }}</div>
    </q-card-section>
    <q-separator />
    <q-card-section>
      <q-form :class="userId === undefined ? 'q-gutter-sm' : 'q-gutter-md'" :aria-label="t('personalVoice.models')" @submit="save">
        <q-linear-progress v-if="loading" indeterminate />
        <q-banner dense rounded>{{ t('personalVoice.modelsIntro') }}</q-banner>
        <div class="personal-llm-fields">
          <q-card flat :bordered="userId !== undefined">
            <q-card-section v-if="userId !== undefined" class="q-py-sm text-subtitle2 text-primary">
              <q-icon name="chat" class="q-mr-sm" />{{ t('personalVoice.llmTitle') }}
            </q-card-section>
            <q-card-section>
              <q-select v-model="values.profile_id" :options="profileOptions"
                :dense="userId === undefined"
                emit-value map-options filled :disable="loading || saving" :label="t('personalVoice.profile')" :hint="t('personalVoice.profileHint')" />
            </q-card-section>
          </q-card>
          <q-card flat :bordered="userId !== undefined">
            <q-card-section v-if="userId !== undefined" class="q-py-sm text-subtitle2 text-primary">
              <q-icon name="record_voice_over" class="q-mr-sm" />{{ t('personalVoice.voiceTitle') }}
            </q-card-section>
            <q-card-section>
              <q-select v-model="voiceSelection" :options="voiceOptions" emit-value map-options filled
                :dense="userId === undefined"
                :disable="loading || saving" :label="t('personalVoice.voiceTitle')"
                :hint="t(values.voice_mode === 'realtime' ? 'personalVoice.nativeHint' : 'personalVoice.ttsHint')">
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
            </q-card-section>
          </q-card>
        </div>
        <div v-if="options.native_voices_error" role="status">{{ t('personalVoice.nativeCatalogError') }}</div>
        <div v-if="error" role="alert">{{ error }}</div>
        <div v-if="saved" role="status">{{ t('personalVoice.saved') }}</div>
        <div class="row justify-end q-gutter-sm">
          <q-btn v-if="!loaded && !loading" flat :label="t('personalVoice.retry')" @click="load" />
          <q-btn type="submit" color="primary" :label="t('personalVoice.save')" :loading="saving" :disable="loading || !loaded" />
        </div>
      </q-form>
    </q-card-section>
  </q-card>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import service, { type PersonalLlmOptions, type PersonalLlmPreferences } from '../services/personalLlmService'

const props = defineProps<{ userId?: number }>()
const { t } = useI18n()
const values = ref<PersonalLlmPreferences>({ profile_id: null, voice_llm_id: null, voice_mode: 'tts', voice_code: null })
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
  loading.value = true; loaded.value = false; saving.value = false; error.value = ''; saved.value = false
  try {
    const [preferences, catalog] = await Promise.all([service.preferences(props.userId), service.options()])
    if (current !== generation) return
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
watch(values, () => { saved.value = false }, { deep: true })
onBeforeUnmount(() => { generation += 1 })
</script>

<style scoped>
.personal-llm-fields { display: grid; gap: 16px; }
.personal-llm-settings--compact .personal-llm-fields { gap: 12px; }
.personal-llm-settings--compact .personal-llm-fields :deep(.q-card__section) { padding: 0; }
@media (min-width: 1024px) {
  .personal-llm-settings--compact .personal-llm-fields {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
