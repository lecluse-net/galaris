<template>
  <q-card flat bordered class="manager-help q-mb-md" role="region" :aria-label="t('harnesses.manager.title')">
      <q-card-section :class="hasWarning ? 'manager-help--warning' : 'manager-help--info'">
        <div class="manager-help__summary">
          <q-icon :name="hasWarning ? 'warning' : 'info'" size="28px" class="manager-help__icon" />
          <div class="manager-help__status" aria-live="polite">
            <div class="text-subtitle1 text-weight-medium">{{ t('harnesses.preferences.managerTitle') }}</div>
            <div v-if="loadFailed" class="text-caption">{{ t('harnesses.manager.loadFailed') }}</div>
            <div v-else-if="!diagnostics" class="text-caption">{{ t('harnesses.manager.checking') }}</div>
            <div v-else class="text-caption">
              {{ t(`harnesses.manager.states.${diagnostics.state}`) }}
              <span v-if="diagnostics.http_status"> (HTTP {{ diagnostics.http_status }})</span>
            </div>
          </div>
          <div class="manager-help__actions">
            <q-btn flat no-caps icon="help_outline" :label="t('harnesses.preferences.help')" @click="helpOpen = true" />
            <q-btn flat no-caps icon="refresh" class="manager-help__action" :label="t('harnesses.preferences.check')"
              :aria-label="t('harnesses.manager.refresh')" :loading="loading" @click.stop="refresh" />
          </div>
        </div>
      </q-card-section>
      <q-card-section>
        <HarnessManagerConfiguration @saved="configurationSaved" />
      </q-card-section>
      <q-separator />
      <HarnessManagerRelease :diagnostics="diagnostics" />
      <q-dialog v-model="helpOpen">
        <q-card class="manager-help__dialog">
          <q-card-section class="galaris-dialog-title row items-center no-wrap">
            <div class="text-h6">{{ t('harnesses.preferences.help') }}</div>
            <q-space /><q-btn v-close-popup flat round dense icon="close" :aria-label="t('common.close')" />
          </q-card-section>
          <q-card-section>
        <p>{{ t('harnesses.setup.intro') }}</p>
        <template v-if="diagnostics">
          <div class="text-caption q-mb-md">{{ t('harnesses.manager.loadedConfig') }}</div>
          <dl class="manager-help__settings">
            <dt><code>HARNESS_MANAGER_URL</code></dt><dd>{{ diagnostics.manager_url || t('harnesses.manager.notSet') }}</dd>
            <dt><code>HARNESS_MANAGER_SECRET</code></dt><dd>{{ t(diagnostics.secret_configured ? 'harnesses.manager.secretPresent' : 'harnesses.manager.secretMissing') }}</dd>
            <dt><code>HARNESS_MANAGER_GALARIS_API_URL</code></dt><dd>{{ diagnostics.galaris_api_url || t('harnesses.manager.notSet') }} <span class="text-caption">({{ diagnostics.api_url_source }})</span></dd>
            <dt><code>APP_HOST/api</code></dt><dd>{{ diagnostics.public_api_url || t('harnesses.manager.notSet') }}</dd>
          </dl>
          <q-banner rounded class="manager-help__notice q-mb-md">
            <div class="text-weight-medium">{{ t('harnesses.manager.harnessToApi') }}</div>
            {{ t('harnesses.manager.apiNotChecked') }}
            <div v-if="diagnostics.api_issue !== 'none'" class="q-mt-sm">
              {{ t(`harnesses.manager.apiIssues.${diagnostics.api_issue}`) }}
            </div>
          </q-banner>
        </template>
        <q-tabs v-model="mode" align="left" active-color="primary" indicator-color="primary" class="q-mt-lg">
          <q-tab name="local" :label="t('harnesses.manager.localTitle')" no-caps />
          <q-tab name="remote" :label="t('harnesses.manager.remoteTitle')" no-caps />
        </q-tabs>
        <q-tab-panels v-model="mode" class="bg-transparent">
          <q-tab-panel v-for="tab in modes" :key="tab" :name="tab" class="q-px-none">
            <p>{{ t(`harnesses.manager.${tab}Intro`) }}</p>
            <ol class="q-pl-lg">
              <li v-for="step in steps" :key="step" class="q-mb-md">
                <div class="text-weight-medium">{{ t(`harnesses.manager.steps.${step}`) }}</div>
                <div>{{ t(`harnesses.manager.${tab}.${step}`) }}</div>
              </li>
            </ol>
          </q-tab-panel>
        </q-tab-panels>
        <q-banner rounded class="manager-help__notice">
          {{ t('harnesses.manager.applyWarning') }}
          <div class="q-mt-sm"><code>make test-harness-management</code></div>
          <div class="q-mt-sm">{{ t('harnesses.manager.finalCheck') }}</div>
        </q-banner>
      </q-card-section>
          <q-card-actions align="right"><q-btn v-close-popup flat :label="t('common.close')" /></q-card-actions>
        </q-card>
      </q-dialog>
  </q-card>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { managerService, type ManagerDiagnostics } from '../services/managerService'
import HarnessManagerConfiguration from './HarnessManagerConfiguration.vue'
import HarnessManagerRelease from './HarnessManagerRelease.vue'

const { t } = useI18n()
const diagnostics = ref<ManagerDiagnostics | null>(null)
const loading = ref(false)
const loadFailed = ref(false)
const hasWarning = computed(() => loadFailed.value || (diagnostics.value !== null && diagnostics.value.state !== 'ok'))
const mode = ref<'local' | 'remote'>('local')
const helpOpen = ref(false)
const modes = ['local', 'remote'] as const
const steps = ['install', 'address', 'secret', 'api', 'network', 'verify'] as const
let disposed = false
let refreshPending = false
let timer: ReturnType<typeof setTimeout> | undefined

function configurationSaved(): void {
  diagnostics.value = null
  if (loading.value) refreshPending = true
  else void refresh()
}

async function refresh(): Promise<void> {
  if (loading.value || disposed) return
  if (timer !== undefined) clearTimeout(timer)
  loading.value = true
  loadFailed.value = false
  try {
    const result = await managerService.diagnostics()
    if (disposed) return
    if (!refreshPending) diagnostics.value = result
  } catch {
    if (!disposed) {
      diagnostics.value = null
      loadFailed.value = true
    }
  } finally {
    if (!disposed) {
      loading.value = false
      timer = setTimeout(() => { void refresh() }, refreshPending ? 0 : 30_000)
      refreshPending = false
    }
  }
}

onMounted(refresh)
onUnmounted(() => { disposed = true; if (timer !== undefined) clearTimeout(timer) })
</script>

<style scoped>
.manager-help { border-radius: 8px; overflow: hidden; }
.manager-help__dialog { width: 800px; max-width: 94vw; }
.manager-help--info { background: var(--solaire-blue-light); border-color: var(--solaire-blue-accent); }
.manager-help--warning { background: var(--solaire-orange-light); border-color: var(--solaire-orange-accent); }
.body--dark .manager-help--info { background: var(--solaire-blue-dark); }
.body--dark .manager-help--warning { background: var(--solaire-orange-dark); }
.manager-help__summary { display: flex; flex-wrap: wrap; align-items: center; flex: 1; min-width: 0; gap: 16px; }
.manager-help__summary .q-btn { max-width: 100%; }
.manager-help__icon { flex-shrink: 0; }
.manager-help__status { flex: 1 1 220px; min-width: 0; overflow-wrap: anywhere; }
.manager-help__action { flex-shrink: 0; }
.manager-help__actions { display: flex; flex-wrap: wrap; gap: 8px; min-width: 0; }
.manager-help__settings { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 2fr); gap: 8px 16px; margin-bottom: 24px; }
.manager-help__settings dt, .manager-help__settings dd { margin: 0; overflow-wrap: anywhere; }
.manager-help__notice { background: var(--solaire-blue-light); }
.body--dark .manager-help__notice { background: var(--solaire-blue-dark); }
@media (max-width: 1023px) { .manager-help__settings { grid-template-columns: minmax(0, 1fr); } .manager-help__settings dd { margin-bottom: 8px; } }
@media (max-width: 599px) {
  .manager-help__summary { gap: 8px; }
  .manager-help__status { flex-basis: 160px; }
  .manager-help__actions { flex-basis: 100%; }
  .manager-help__action { flex: 1 1 auto; padding: 4px 8px; }
}
</style>
