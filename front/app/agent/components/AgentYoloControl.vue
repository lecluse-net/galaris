<template>
  <div class="q-mb-md">
    <q-toggle :model-value="agent.yolo" :disable="disabled || saving" :label="t('agent.yolo.label')"
      @update:model-value="toggle" />
    <q-badge v-if="agent.yolo" class="yolo-badge">{{ t('agent.yolo.active') }}</q-badge>
    <div v-if="error" role="alert">{{ t('agent.yolo.error') }}</div>
    <q-dialog v-model="confirmOpen">
      <q-card style="width: 560px; max-width: 95vw">
        <q-card-section class="galaris-dialog-title row items-center">
          <div class="text-h6">{{ t('agent.yolo.confirmTitle') }}</div>
          <q-space /><q-btn v-close-popup flat round dense icon="close" :aria-label="t('common.close')" />
        </q-card-section>
        <q-card-section><p>{{ t('agent.yolo.warning') }}</p></q-card-section>
        <q-card-actions align="right">
          <q-btn v-close-popup flat :label="t('common.cancel')" />
          <q-btn :label="t('agent.yolo.activate')" :loading="saving" @click="save(true)" />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, onBeforeUnmount } from 'vue'
import { useI18n } from 'vue-i18n'
import { agentService, type Agent } from '../services/agentService'
const { agent, disabled = false } = defineProps<{ agent: Agent; disabled?: boolean }>()
const emit = defineEmits<{ changed: [] }>()
const { t } = useI18n()
const confirmOpen = ref(false)
const saving = ref(false)
const error = ref(false)
let generation = 0
watch(() => agent.id, () => { generation++; confirmOpen.value = false; error.value = false; saving.value = false })
onBeforeUnmount(() => { generation++ })
function toggle(enabled: boolean) {
  if (enabled) confirmOpen.value = true
  else void save(false)
}
async function save(enabled: boolean) {
  const id = agent.id
  const current = ++generation
  saving.value = true
  error.value = false
  try {
    await agentService.setYolo(id, enabled, agent.authorization_version, enabled)
    if (generation === current && agent.id === id) { confirmOpen.value = false; emit('changed') }
  } catch { if (generation === current && agent.id === id) error.value = true }
  finally { if (generation === current) saving.value = false }
}
</script>

<style scoped>
.yolo-badge { background: var(--solaire-red-light); color: var(--solaire-red-accent); }
:global(body.body--dark) .yolo-badge { background: var(--solaire-red-dark); }
</style>
