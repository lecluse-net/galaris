<template>
  <main class="q-pa-md mcp-settings">
    <header class="row items-center q-gutter-sm q-mb-md">
      <q-btn flat round dense color="primary" icon="arrow_back" :aria-label="t('mcpBack')" @click="api.closeMcpSettings()" />
      <h1 class="text-h5 q-ma-none">{{ t('mcpTitle') }}</h1>
    </header>
    <p class="text-body2">{{ t('mcpIntro') }}</p>
    <p v-if="state.server" class="text-body2 text-weight-medium">{{ state.server }}</p>
    <p v-else class="text-body2">{{ t('mcpConnectFirst') }}</p>
    <div class="row q-gutter-sm q-mb-md">
      <q-btn color="primary" icon="refresh" :label="t('mcpDiscover')" :loading="state.scanning" :disable="pending !== ''" @click="perform(() => api.discoverMcp())" />
      <q-btn outline color="primary" icon="file_open" :label="t('mcpImport')" :disable="state.scanning || pending !== ''" @click="perform(() => api.importMcp())" />
    </div>
    <q-banner v-if="state.error || failed" rounded class="error-banner q-mb-md" role="alert">
      {{ t(state.error || 'mcpServerError') }}
    </q-banner>
    <p v-if="state.unreadable" role="status">{{ t('mcpUnreadable', { count: state.unreadable }) }}</p>
    <q-list v-if="state.entries.length" bordered separator>
      <q-item v-for="entry in state.entries" :key="entry.id">
        <q-item-section class="mcp-entry">
          <q-item-label>{{ entry.name }}</q-item-label>
          <q-item-label caption>{{ t('mcpSource', { source: entry.source, transport: t('mcpTransport_' + entry.transport) }) }}</q-item-label>
          <q-item-label caption aria-live="polite">{{ t(entry.status) }}</q-item-label>
        </q-item-section>
        <q-item-section side>
          <q-toggle color="primary" :model-value="entry.shared" :disable="controlsDisabled"
            :aria-label="t('mcpShare', { name: entry.name })" @update:model-value="share(entry.id, $event)" />
        </q-item-section>
      </q-item>
    </q-list>
    <p v-else-if="!state.scanning" role="status">{{ t('mcpEmpty') }}</p>
  </main>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import type { LocalMcpState } from '../src/contracts'

const api = window.galarisDesktop
const { t } = useI18n()
const state = ref<LocalMcpState>({ server: '', entries: [], scanning: true, unreadable: 0, error: '' })
const pending = ref('')
const failed = ref(false)
const controlsDisabled = computed(() => !state.value.server || state.value.scanning || pending.value !== '')
let revision = 0
onUnmounted(api.onMcpState(value => { revision++; state.value = value }))
onMounted(() => {
  const initialRevision = revision
  void perform(async () => {
    const snapshot = await api.mcpState()
    if (revision === initialRevision) state.value = snapshot
  })
})
async function perform(action: () => Promise<void>): Promise<void> {
  failed.value = false
  try { await action() } catch { failed.value = true; state.value.scanning = false }
}
async function share(id: string, enabled: boolean): Promise<void> {
  if (controlsDisabled.value) return
  pending.value = id
  try { await perform(() => api.shareMcp(id, enabled)) } finally { pending.value = '' }
}
</script>

<style scoped>
.mcp-settings { max-width: 720px; margin-inline: auto; }
.mcp-entry { overflow-wrap: anywhere; }
</style>
