<template>
  <q-dialog allow-focus-outside v-model="dialogOpen">
    <q-card class="task-form-dialog">
      <q-card-section class="galaris-dialog-title row items-center">
        <div class="text-h6">{{ isEdit ? $t('task.form.editTitle') : $t('task.form.createTitle') }}</div>
        <q-space />
        <q-btn icon="close" :aria-label="$t('common.close')" flat round dense v-close-popup class="text-white" />
      </q-card-section>

      <q-separator />

      <q-card-section>
        <q-form @submit="onSubmit()" class="q-gutter-y-md">
          <q-input
            v-model="form.label"
            :label="$t('task.form.label')"
            filled
            :rules="[val => !!val || $t('task.form.labelRequired')]"
            maxlength="400"
            counter
            hide-bottom-space
          />

          <AgentSelect
            :model-value="form.agent_id ?? null"
            @update:model-value="value => form.agent_id = value ?? undefined"
            :options="agentOptions"
            :label="$t('task.form.assignedAgent')"
            filled
            emit-value
            map-options
            clearable
          />

          <RichTextEditor v-model="form.objective" :aria-label="$t('task.form.objective')" />

          <div class="row q-col-gutter-md q-mt-none">
            <div class="col-6">
              <q-select
                v-model="form.forced_route"
                :options="routeOptions"
                :label="$t('task.form.forcedRoute')"
                :hint="$t('task.form.forcedHint')"
                filled
                emit-value
                map-options
              />
            </div>
            <div class="col-6">
              <q-select
                v-model="form.forced_effort"
                :options="effortOptions"
                :label="$t('task.form.forcedEffort')"
                :hint="$t('task.form.forcedHint')"
                filled
                emit-value
                map-options
              />
            </div>
          </div>

          <q-toggle
            v-model="form.auto_approve"
            :label="$t('task.form.autoApprove')"
            color="orange"
          />
          <div class="text-caption text-grey-7 q-mt-none">
            {{ $t('task.form.autoApproveHint') }}
          </div>
        </q-form>
      </q-card-section>

      <q-card-actions align="right" class="q-pa-md galaris-dialog-actions">
        <q-btn flat :label="$t('common.cancel')" color="grey" v-close-popup />
        <q-btn
          v-if="canEdit && !isEdit"
          outline
          color="green"
          icon="play_arrow"
          :label="$t('task.form.createAndRun')"
          :loading="loading"
          @click="onSubmit(true)"
        />
        <q-btn v-if="canEdit" :label="isEdit ? $t('common.edit') : $t('common.create')" color="primary" :loading="loading" @click="onSubmit()" />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { RichTextEditor } from '@/core/util'
import { ref, computed, watch, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import type { Task, TaskCreate, TaskUpdate, ForcedRoute, Effort } from '../types'
import { agentService } from '@/app/agent/services/agentService'
import { AgentSelect } from '@/app/agent'
import type { Agent } from '@/app/agent/services/agentService'

interface FormData {
  label: string
  agent_id?: number
  objective: string
  forced_route: ForcedRoute | null
  forced_effort: Effort | null
  auto_approve: boolean
}

const props = defineProps<{
  modelValue: boolean
  task?: Task | null
  loading?: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  'submit': [data: TaskCreate | TaskUpdate, options?: { runAfterCreate?: boolean }]
}>()

const dialogOpen = computed({
  get: () => props.modelValue,
  set: (val) => emit('update:modelValue', val)
})

const isEdit = computed(() => !!props.task)

const defaultForm: FormData = {
  label: '',
  agent_id: undefined,
  objective: '',
  forced_route: null,
  forced_effort: null,
  auto_approve: false
}

const form = ref<FormData>({ ...defaultForm })
const agents = ref<Agent[]>([])
const { t } = useI18n()
const privilegeStore = usePrivilegeStore()
const canEdit = computed(() => privilegeStore.hasPrivilege(privileges.TASK_EDIT))

const agentOptions = computed(() =>
  agents.value.map(agent => ({
    label: `${agent.first_name} ${agent.last_name}`.trim(),
    value: agent.id
  }))
)

const routeOptions = computed(() => [
  { label: t('task.form.auto'), value: null },
  { label: t('task.form.routeExec'), value: 'EXEC' },
  { label: t('task.form.routePlan'), value: 'PLAN' }
])

const effortOptions = computed(() => [
  { label: t('task.form.auto'), value: null },
  { label: t('task.dispatch.effortLevels.standard'), value: 'standard' },
  { label: t('task.dispatch.effortLevels.high'), value: 'high' }
])

async function loadAgents() {
  try {
    const response = await agentService.getAgents()
    agents.value = response.data
  } catch (error) {
    console.error('Failed to load agents:', error)
  }
}

onMounted(() => {
  loadAgents()
})

watch(() => props.task, (task) => {
  if (task) {
    form.value = {
      label: task.label,
      agent_id: task.agent_id,
      objective: task.objective || '',
      forced_route: task.forced_route ?? null,
      forced_effort: task.forced_effort ?? null,
      auto_approve: task.auto_approve ?? false
    }
  } else {
    form.value = { ...defaultForm }
  }
}, { immediate: true })

watch(() => props.modelValue, (open) => {
  if (open && !props.task) {
    form.value = { ...defaultForm }
  }
})

function onSubmit(runAfterCreate = false) {
  if (!form.value.label.trim()) return

  const data: TaskCreate | TaskUpdate = {
    ...(isEdit.value && props.task ? { expected_revision: props.task.revision } : {}),
    label: form.value.label.trim(),
    agent_id: form.value.agent_id || undefined,
    objective: form.value.objective.trim() || undefined,
    // Explicit null returns to automatic routing and clears the backend override.
    forced_route: form.value.forced_route,
    forced_effort: form.value.forced_effort,
    auto_approve: form.value.auto_approve,
    // New tasks start human-paused unless they are run immediately. The backend derives
    // the "user" pause reason from paused.
    status: isEdit.value ? undefined : 'CREATE',
    paused: isEdit.value ? undefined : !runAfterCreate,
  }

  emit('submit', data, { runAfterCreate })
}
</script>

<style scoped>
.task-form-dialog {
  width: min(720px, calc(100vw - 32px));
  max-width: 720px;
}
</style>
