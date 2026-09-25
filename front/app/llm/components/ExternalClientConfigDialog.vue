<template>
  <q-dialog :model-value="true" @hide="emit('close')">
    <q-card class="client-config-dialog">
      <q-card-section class="galaris-dialog-title row items-center no-wrap">
        <div class="text-h6">{{ t('clientConfig.title') }}</div>
        <q-space />
        <q-btn flat round dense icon="close" :aria-label="t('common.close')" v-close-popup />
      </q-card-section>
      <q-card-section>
        <p>{{ t('clientConfig.intro') }}</p>
        <div v-if="loading" role="status" class="row items-center q-gutter-sm">
          <q-spinner color="primary" />
          <span>{{ t('clientConfig.loading') }}</span>
        </div>
        <q-banner v-else-if="loadError" class="client-config-error" rounded>
          {{ t('clientConfig.loadError') }}
          <template #action>
            <q-btn flat :label="t('common.retry')" @click="loadProfiles" />
          </template>
        </q-banner>
        <p v-else-if="!profiles.length" role="status">{{ t('clientConfig.empty') }}</p>
        <template v-else>
          <div class="row q-col-gutter-md">
            <q-select
              v-model="profileCode"
              :options="profiles.map(profile => profile.code)"
              :label="t('clientConfig.profile')"
              outlined
              class="col-12 col-sm-6"
            />
            <q-select
              v-model="model"
              :options="selectedProfile?.models ?? []"
              :label="t('clientConfig.model')"
              outlined
              class="col-12 col-sm-6"
            />
          </div>
          <q-tabs v-model="client" dense align="left" class="q-mt-md" active-color="primary">
            <q-tab name="claude" :label="t('clientConfig.claude')" />
            <q-tab name="codex" :label="t('clientConfig.codex')" />
          </q-tabs>
          <template v-if="configuration">
            <p class="text-body2 q-mt-md">{{ t('clientConfig.mergeHint') }}</p>
            <p v-if="client === 'codex'" class="text-body2">{{ t('clientConfig.codexHint') }}</p>
            <p v-else-if="selectedProfile && selectedProfile.models.length < 4" class="text-body2">
              {{ t('clientConfig.missingTiers') }}
            </p>
            <div class="row items-center justify-between q-mb-sm">
              <code>{{ configPath }}</code>
              <q-btn flat color="primary" icon="content_copy" :label="t('clientConfig.copy')" @click="copy(configuration)" />
            </div>
            <q-input
              :model-value="configuration"
              :label="t('clientConfig.content')"
              readonly outlined type="textarea" :rows="12"
              input-class="client-config-code"
            />
            <p class="text-body2 q-mt-md">{{ t('clientConfig.tokenHint') }}</p>
            <div class="row items-center justify-between q-mb-sm">
              <code v-if="client === 'claude'">.claude/settings.local.json</code>
              <span v-else>{{ t('clientConfig.shell') }}</span>
              <q-btn flat color="primary" icon="content_copy" :label="t('clientConfig.copyTokenSetup')" @click="copy(tokenSetup)" />
            </div>
            <q-input
              :model-value="tokenSetup"
              :label="t('clientConfig.tokenSetup')"
              readonly outlined type="textarea" :rows="client === 'claude' ? 5 : 2"
              input-class="client-config-code"
            />
            <p v-if="client === 'claude'" class="text-caption q-mt-sm">{{ t('clientConfig.localFileHint') }}</p>
          </template>
        </template>
      </q-card-section>
      <q-card-actions class="galaris-dialog-actions" align="right">
        <q-btn flat color="primary" :label="t('common.close')" v-close-popup />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import { isCancelledRequest } from '@/core/api'
import { buildClientConfig, clientProfiles, clientTokenSetup, type ClientProfile, type ExternalClient } from '../clientConfig'
import { getProfileModelSelectors } from '../services/profileCatalogService'

const emit = defineEmits<{ close: [] }>()
const { t } = useI18n()
const $q = useQuasar()
const client = ref<ExternalClient>('claude')
const profiles = ref<ClientProfile[]>([])
const profileCode = ref('')
const model = ref('')
const loading = ref(true)
const loadError = ref(false)
let request: AbortController | undefined
const selectedProfile = computed(() => profiles.value.find(profile => profile.code === profileCode.value))
watch(selectedProfile, profile => { model.value = profile?.models[0] ?? '' }, { flush: 'sync' })
const configPath = computed(() => client.value === 'claude' ? '.claude/settings.json' : '~/.codex/config.toml')
const configuration = computed(() => {
  const profile = selectedProfile.value
  return profile?.models.includes(model.value)
    ? buildClientConfig(client.value, window.location.origin, profile, model.value)
    : ''
})
const tokenSetup = computed(() => clientTokenSetup(client.value))

async function loadProfiles(): Promise<void> {
  request?.abort()
  const current = new AbortController()
  request = current
  loading.value = true
  loadError.value = false
  profiles.value = []
  profileCode.value = ''
  try {
    const selectors = await getProfileModelSelectors(current.signal)
    if (current.signal.aborted) return
    profiles.value = clientProfiles(selectors)
    profileCode.value = profiles.value[0]?.code ?? ''
  } catch (error) {
    if (!current.signal.aborted && !isCancelledRequest(error)) loadError.value = true
  } finally {
    if (request === current && !current.signal.aborted) loading.value = false
  }
}

async function copy(content: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(content)
    $q.notify({ type: 'positive', message: t('clientConfig.copied') })
  } catch {
    $q.notify({ type: 'negative', message: t('clientConfig.copyFailed') })
  }
}

onMounted(loadProfiles)
onBeforeUnmount(() => request?.abort())
</script>

<style scoped>
.client-config-dialog {
  width: 800px;
  max-width: calc(100vw - 32px);
}

.client-config-dialog code {
  overflow-wrap: anywhere;
}

:deep(.client-config-code) {
  font-family: monospace;
  white-space: pre;
}

.client-config-error {
  background: var(--solaire-red-light);
}

body.body--dark .client-config-error {
  background: var(--solaire-red-dark);
}
</style>
