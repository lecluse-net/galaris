<template>
  <div>
    <AgentSelect v-model="model" :options="options" :label="label" :loading="agents.loading" outlined />
    <q-banner v-if="failed" role="alert" class="q-mt-sm">
      {{ t('common.viewLoadError') }}
      <template #action><q-btn outline color="primary" :label="t('common.retry')" @click="load" /></template>
    </q-banner>
  </div>
</template>
<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import AgentSelect from './AgentSelect.vue'
import { useAgentChoices } from '../composables/useAgentChoices'
defineProps<{ label: string }>()
const model = defineModel<number | null>({ required: true })
const { t } = useI18n()
const agents = useAgentChoices(), failed = ref(false)
const options = computed(() => agents.agents.map(agent => ({ value: agent.id, label: agent.label, hasAvatar: agent.has_avatar })))
async function load(): Promise<void> {
  failed.value = false
  try { await agents.fetchAgents() } catch { failed.value = true }
}
onMounted(load)
</script>
