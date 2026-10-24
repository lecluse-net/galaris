<template>
  <q-dialog :model-value="skill !== null" @update:model-value="value => { if (!value) skill = null }">
    <q-card class="galaris-dialog-card" style="width: 560px; max-width: 95vw">
      <q-toolbar class="galaris-dialog-title bg-primary text-white">
        <q-toolbar-title>{{ t('skills.personal.assign') }}</q-toolbar-title>
        <q-btn v-close-popup flat round dense icon="close" :aria-label="t('common.close')" />
      </q-toolbar>
      <q-card-section class="galaris-dialog-body q-gutter-md">
        <p>{{ t('skills.personal.assignConfirm', { label: skill?.label ?? '' }) }}</p>
        <q-spinner v-if="loading" color="primary" />
        <q-banner v-if="error" rounded role="alert" class="bg-negative text-white">{{ error }}</q-banner>
        <q-select v-model="owner" :options="owners" option-value="id" option-label="label" emit-value map-options
          outlined :label="t('skills.personal.owner')" :disable="loading || saving || cleanupPending" />
        <q-input v-model="code" outlined :label="t('skills.code')" :disable="loading || saving || cleanupPending" />
      </q-card-section>
      <q-card-actions align="right" class="galaris-dialog-actions">
        <q-btn v-close-popup outline color="primary" :label="t('common.cancel')" />
        <q-btn v-if="!ready" outline color="primary" :label="t('skills.personal.retry')" :loading="loading" @click="load" />
        <q-btn v-else color="primary" :label="t('skills.personal.assign')" :loading="saving"
          :disable="owner === null || !code.trim()" @click="save" />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { apiErrorDetail } from '@/core/api'
import { getAgentSelection, type AgentSelectionOption } from '@/app/agent'
import { skillService, type Skill } from '../services/skillService'

const skill = defineModel<Skill | null>({ required: true })
const emit = defineEmits<{ converted: [] }>()
const { t } = useI18n()
const owner = ref<number | null>(null)
const code = ref('')
const owners = ref<AgentSelectionOption[]>([])
const revision = ref(0)
const ready = ref(false)
const loading = ref(false)
const saving = ref(false)
const cleanupPending = ref(false)
const error = ref('')
let generation = 0
let operation = crypto.randomUUID()

watch([owner, code], () => { operation = crypto.randomUUID() })
watch(skill, value => {
  ++generation
  owner.value = null
  code.value = value?.code ?? ''
  ready.value = false
  error.value = ''
  saving.value = false
  cleanupPending.value = false
  operation = crypto.randomUUID()
  if (value) void load()
})

async function load(): Promise<void> {
  if (!skill.value) return
  const id = skill.value.id
  const current = ++generation
  loading.value = true
  error.value = ''
  try {
    const [agents, response] = await Promise.all([getAgentSelection('management'), skillService.getSkill(id)])
    if (current !== generation) return
    owners.value = agents
    revision.value = response.data.revision
    ready.value = true
  } catch (cause) {
    if (current === generation) error.value = apiErrorDetail(cause) ?? t('skills.error')
  } finally {
    if (current === generation) loading.value = false
  }
}

async function save(): Promise<void> {
  if (!skill.value || owner.value === null || saving.value || !ready.value) return
  const current = generation
  saving.value = true
  error.value = ''
  try {
    const response = await skillService.assignSkillOwner(skill.value.id, owner.value, revision.value, operation, code.value.trim())
    emit('converted')
    if (current !== generation) return
    cleanupPending.value = response.data.cleanup_pending
    if (response.data.cleanup_pending) error.value = t('skills.personal.cleanupPending')
    else skill.value = null
  } catch (cause) {
    if (current === generation) error.value = apiErrorDetail(cause) ?? t('skills.error')
  } finally {
    if (current === generation) saving.value = false
  }
}
</script>
