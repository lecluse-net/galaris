<template>
  <section>
    <div v-if="loading" class="row justify-center q-pa-lg">
      <q-spinner color="primary" size="36px" />
    </div>

    <q-banner v-else-if="!agent" rounded class="bg-grey-2 text-grey-8">
      {{ t('hermes.loadError') }}
    </q-banner>

    <template v-else>
      <div class="q-gutter-y-md">
        <q-card flat bordered>
          <q-card-section class="q-py-sm bg-grey-2">
            <div class="text-subtitle2 text-primary">
              <q-icon name="dashboard" class="q-mr-sm" />{{ t('hermes.dashboardTitle') }}
            </div>
          </q-card-section>
          <q-card-section class="q-gutter-y-sm">
            <div class="row q-col-gutter-md items-center">
              <div class="col-12 col-sm-6">
                <q-toggle
                  v-model="config.hermes_dashboard_enabled"
                  color="secondary"
                  :label="t('hermes.dashboardEnabled')"
                />
              </div>
              <div v-if="config.hermes_dashboard_enabled" class="col-12 col-sm-6">
                <q-input
                  v-model.number="config.hermes_dashboard_port"
                  dense filled clearable type="number"
                  :label="t('hermes.dashboardPort')"
                />
              </div>
            </div>
            <div v-if="config.hermes_dashboard_enabled" class="row q-col-gutter-md">
              <div class="col-12 col-sm-5">
                <q-input
                  v-model="config.hermes_dashboard_username"
                  dense filled :label="t('hermes.dashboardUsername')"
                />
              </div>
              <div class="col-12 col-sm-7">
                <q-input
                  v-model="config.hermes_dashboard_password"
                  dense filled autocomplete="new-password"
                  :type="showPassword ? 'text' : 'password'"
                  :label="dashboardPasswordLabel"
                >
                  <template #append>
                    <q-btn
                      dense flat round
                      :icon="showPassword ? 'visibility_off' : 'visibility'"
                      :aria-label="t('hermes.togglePassword')"
                      @click="showPassword = !showPassword"
                    />
                    <q-btn
                      dense flat round icon="auto_fix_high"
                      :aria-label="t('hermes.generatePassword')"
                      @click="generatePassword"
                    />
                  </template>
                </q-input>
              </div>
            </div>
            <div class="text-caption text-grey-7">{{ t('hermes.dashboardHint') }}</div>
          </q-card-section>
        </q-card>

        <q-card flat bordered>
          <q-card-section class="q-py-sm bg-grey-2 row items-center">
            <div class="text-subtitle2 text-primary">
              <q-icon name="tune" class="q-mr-sm" />{{ t('hermes.envTitle') }}
            </div>
            <q-space />
            <q-btn flat icon="add" :label="t('hermes.envAdd')" @click="addEnvPair" />
          </q-card-section>
          <q-card-section>
            <div class="text-caption text-grey-7 q-mb-sm">{{ t('hermes.envHint') }}</div>
            <div
              v-for="(pair, index) in envPairs"
              :key="index"
              class="row q-col-gutter-sm items-center q-mb-sm"
            >
              <div class="col-12 col-sm-5">
                <q-input v-model="pair.key" dense filled :label="t('hermes.envKey')" />
              </div>
              <div class="col-10 col-sm-6">
                <q-input
                  v-model="pair.value" dense filled type="password" autocomplete="new-password"
                  :label="t('hermes.envValue')" :hint="t('hermes.envWriteOnlyHint')"
                />
              </div>
              <div class="col-2 col-sm-1">
                <q-btn flat round color="negative" icon="delete" @click="removeEnvPair(index)" />
              </div>
            </div>
          </q-card-section>
        </q-card>

        <CodeEditor
          v-model="config.hermes_config"
          language="yaml"
          :label="t('harnessSettings.hermes.fields.defaultConfig')"
        />
        <CodeEditor
          v-model="config.hermes_compose"
          language="yaml"
          :label="t('harnessSettings.hermes.fields.defaultCompose')"
        />
      </div>

      <div class="row justify-end q-mt-md q-gutter-sm">
        <q-btn
          v-if="showCancel"
          flat :label="t('common.cancel')" color="primary"
          @click="emit('cancel')"
        />
        <q-btn
          v-if="canEdit"
          color="primary"
          :label="t('common.save')"
          :loading="saving"
          @click="saveConfig"
        />
      </div>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'

import { privileges, usePrivilegeStore } from '@/core/authorize'
import { CodeEditor } from '@/core/util'
import hermesService, {
  type HermesAgent,
  type HermesConfigUpdate,
} from '../services/hermesService'

interface EnvPair {
  key: string
  value: string
}

const props = withDefaults(defineProps<{
  agentId: number
  initialAgent?: HermesAgent | null
  showCancel?: boolean
}>(), {
  initialAgent: null,
  showCancel: false,
})

const emit = defineEmits<{
  updated: [agent: HermesAgent]
  cancel: []
}>()

const $q = useQuasar()
const { t } = useI18n()
const privilegeStore = usePrivilegeStore()
const canEdit = computed(() => privilegeStore.hasPrivilege(privileges.AGENT_EDIT))
const agent = ref<HermesAgent | null>(null)
const loading = ref(false)
const saving = ref(false)
const showPassword = ref(false)
const envPairs = ref<EnvPair[]>([])
const config = reactive({
  hermes_dashboard_enabled: false,
  hermes_dashboard_port: null as number | null,
  hermes_dashboard_username: '',
  hermes_dashboard_password: '',
  hermes_dashboard_password_configured: false,
  hermes_config: '',
  hermes_compose: '',
})

const dashboardPasswordLabel = computed(() => config.hermes_dashboard_password_configured
  ? t('hermes.dashboardPasswordChange')
  : t('hermes.dashboardPassword'))

function hydrate(value: HermesAgent): void {
  agent.value = value
  Object.assign(config, {
    hermes_dashboard_enabled: value.hermes_dashboard_enabled ?? false,
    hermes_dashboard_port: value.hermes_dashboard_port ?? null,
    hermes_dashboard_username: value.hermes_dashboard_username || '',
    hermes_dashboard_password: '',
    hermes_dashboard_password_configured: value.hermes_dashboard_password_configured ?? false,
    hermes_config: value.hermes_config || '',
    hermes_compose: value.hermes_compose || '',
  })
  envPairs.value = Object.entries(value.hermes_data_env || {})
    .map(([key, envValue]) => ({ key, value: String(envValue) }))
  showPassword.value = false
}

async function loadAgent(): Promise<void> {
  if (props.initialAgent?.id === props.agentId) {
    hydrate(props.initialAgent)
    return
  }
  loading.value = true
  try {
    const match = (await hermesService.listAgents()).data.find(item => item.id === props.agentId)
    if (match) hydrate(match)
    else agent.value = null
  } catch {
    agent.value = null
    $q.notify({ type: 'negative', message: t('hermes.loadError') })
  } finally {
    loading.value = false
  }
}

function addEnvPair(): void {
  envPairs.value.push({ key: '', value: '' })
}

function removeEnvPair(index: number): void {
  envPairs.value.splice(index, 1)
}

function generatePassword(): void {
  if (!config.hermes_dashboard_username) config.hermes_dashboard_username = 'admin'
  const alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@#$%*-_=+'
  const bytes = new Uint8Array(24)
  crypto.getRandomValues(bytes)
  config.hermes_dashboard_password = Array.from(
    bytes,
    byte => alphabet.charAt(byte % alphabet.length),
  ).join('')
  showPassword.value = true
}

async function saveConfig(): Promise<void> {
  if (!agent.value || !canEdit.value) return
  const hermesDataEnv: Record<string, string> = {}
  for (const pair of envPairs.value) {
    const key = pair.key.trim()
    if (key) hermesDataEnv[key] = pair.value
  }
  const payload: HermesConfigUpdate = {
    hermes_dashboard_enabled: config.hermes_dashboard_enabled,
    hermes_dashboard_port: config.hermes_dashboard_port,
    hermes_dashboard_username: config.hermes_dashboard_username || null,
    hermes_dashboard_password: config.hermes_dashboard_password || null,
    hermes_config: config.hermes_config || null,
    hermes_compose: config.hermes_compose || null,
    hermes_data_env: hermesDataEnv,
  }
  saving.value = true
  try {
    const updated = (await hermesService.updateConfig(agent.value.id, payload)).data
    hydrate(updated)
    emit('updated', updated)
    $q.notify({ type: 'positive', message: t('hermes.saved') })
  } catch {
    $q.notify({ type: 'negative', message: t('hermes.saveError') })
  } finally {
    saving.value = false
  }
}

watch(
  () => [props.agentId, props.initialAgent] as const,
  () => void loadAgent(),
  { immediate: true },
)
</script>
