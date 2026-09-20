<template>
  <div>
    <div class="text-h6 q-mb-xs">{{ t('params.logs.title') }}</div>
    <div class="text-body2 text-grey-7 q-mb-lg">{{ t('params.logs.subtitle') }}</div>

    <q-banner rounded class="logs-warning q-mb-lg">
      <template #avatar>
        <q-icon name="warning_amber" color="warning" size="28px" />
      </template>
      <div class="text-weight-medium">{{ t('params.logs.warningTitle') }}</div>
      <div class="text-caption q-mt-xs">{{ t('params.logs.warningText') }}</div>
    </q-banner>

    <div class="row q-col-gutter-md items-stretch">
      <div class="col-12 col-md-4">
        <q-card flat bordered class="cleanup-card full-height">
          <q-card-section class="row items-start no-wrap q-gutter-md">
            <q-avatar color="blue-1" text-color="primary" icon="task_alt" />
            <div>
              <div class="text-subtitle1 text-weight-medium">{{ t('params.logs.tasks.title') }}</div>
              <div class="text-body2 text-grey-7 q-mt-xs">{{ t('params.logs.tasks.description') }}</div>
            </div>
          </q-card-section>
          <q-space />
          <q-card-section class="q-pt-none">
            <div class="preserved-note">
              <q-icon name="shield" color="positive" size="18px" />
              <span>{{ t('params.logs.tasks.preserved') }}</span>
            </div>
          </q-card-section>
          <q-card-actions align="right" class="cleanup-actions">
            <q-btn
              v-if="canPurgeTasks"
              outline
              no-caps
              color="negative"
              icon="delete_sweep"
              :label="t('params.logs.tasks.button')"
              @click="openCleanup('tasks')"
            />
          </q-card-actions>
        </q-card>
      </div>

      <div class="col-12 col-md-4">
        <q-card flat bordered class="cleanup-card full-height">
          <q-card-section class="row items-start no-wrap q-gutter-md">
            <q-avatar color="deep-purple-1" text-color="deep-purple" icon="psychology" />
            <div>
              <div class="text-subtitle1 text-weight-medium">{{ t('params.logs.llm.title') }}</div>
              <div class="text-body2 text-grey-7 q-mt-xs">{{ t('params.logs.llm.description') }}</div>
            </div>
          </q-card-section>
          <q-space />
          <q-card-section class="q-pt-none">
            <div class="preserved-note">
              <q-icon name="shield" color="positive" size="18px" />
              <span>{{ t('params.logs.llm.preserved') }}</span>
            </div>
          </q-card-section>
          <q-card-actions align="right" class="cleanup-actions">
            <q-btn
              v-if="canPurgeLlmCalls"
              outline
              no-caps
              color="negative"
              icon="delete_sweep"
              :label="t('params.logs.llm.button')"
              @click="openCleanup('llm')"
            />
          </q-card-actions>
        </q-card>
      </div>

      <div class="col-12 col-md-4">
        <q-card flat bordered class="cleanup-card full-height">
          <q-card-section class="row items-start no-wrap q-gutter-md">
            <q-avatar color="red-1" text-color="negative" icon="error_outline" />
            <div>
              <div class="text-subtitle1 text-weight-medium">{{ t('params.logs.incidents.title') }}</div>
              <div class="text-body2 text-grey-7 q-mt-xs">{{ t('params.logs.incidents.description') }}</div>
            </div>
          </q-card-section>
          <q-space />
          <q-card-section class="q-pt-none">
            <div class="preserved-note">
              <q-icon name="shield" color="positive" size="18px" />
              <span>{{ t('params.logs.incidents.preserved') }}</span>
            </div>
          </q-card-section>
          <q-card-actions align="right" class="cleanup-actions">
            <q-btn
              v-if="canPurgeIncidents"
              outline
              no-caps
              color="negative"
              icon="delete_sweep"
              :label="t('params.logs.incidents.button')"
              @click="openCleanup('incidents')"
            />
          </q-card-actions>
        </q-card>
      </div>
    </div>

    <q-dialog :model-value="cleanupTarget !== null" @update:model-value="closeDialog">
      <q-card class="cleanup-dialog">
        <q-card-section class="galaris-dialog-title row items-center no-wrap">
          <q-icon name="warning" size="28px" />
          <span class="q-ml-sm text-h6">{{ confirmationTitle }}</span>
          <q-space />
          <q-btn v-close-popup flat round dense icon="close" :aria-label="t('common.close')" />
        </q-card-section>
        <q-card-section>
          <p>{{ confirmationMessage }}</p>
          <p class="text-caption text-grey-7">{{ t('params.logs.irreversible') }}</p>
        </q-card-section>
        <q-card-actions class="galaris-dialog-actions" align="right">
          <q-btn flat no-caps :label="t('common.cancel')" color="grey-7" v-close-popup />
          <q-btn
            v-if="cleanupAllowed"
            flat
            no-caps
            :label="t('params.logs.confirm')"
            color="negative"
            :loading="cleanupLoading"
            @click="confirmCleanup"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import { llmCallService } from '@/app/llm/services/llmCallService'
import { taskService } from '@/app/task/services/taskService'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import { logCleanupService } from '../services/logCleanupService'

type CleanupTarget = 'tasks' | 'llm' | 'incidents'

const { t } = useI18n()
const $q = useQuasar()
const privilegeStore = usePrivilegeStore()
const cleanupTarget = ref<CleanupTarget | null>(null)
const cleanupLoading = ref(false)

const canPurgeTasks = computed(() => privilegeStore.hasPrivilege(privileges.TASK_PURGE))
const canPurgeLlmCalls = computed(() => privilegeStore.hasPrivilege(privileges.LLM_CALL_PURGE))
const canPurgeIncidents = computed(() => privilegeStore.hasPrivilege(privileges.INCIDENT_PURGE))
const cleanupAllowed = computed(() => cleanupTarget.value !== null && canPurge(cleanupTarget.value))
const confirmationTitle = computed(() => cleanupTarget.value
  ? t(`params.logs.${cleanupTarget.value}.confirmTitle`)
  : '')
const confirmationMessage = computed(() => cleanupTarget.value
  ? t(`params.logs.${cleanupTarget.value}.confirmMessage`)
  : '')

function openCleanup(target: CleanupTarget): void {
  if (canPurge(target)) cleanupTarget.value = target
}

function canPurge(target: CleanupTarget): boolean {
  if (target === 'tasks') return canPurgeTasks.value
  if (target === 'llm') return canPurgeLlmCalls.value
  return canPurgeIncidents.value
}

function closeDialog(open: boolean): void {
  if (!open && !cleanupLoading.value) cleanupTarget.value = null
}

async function confirmCleanup(): Promise<void> {
  const target = cleanupTarget.value
  if (!target) return

  if (!canPurge(target)) {
    $q.notify({ type: 'negative', message: t('params.logs.denied') })
    cleanupTarget.value = null
    return
  }

  cleanupLoading.value = true
  try {
    if (target === 'tasks') await taskService.cleanup()
    else if (target === 'llm') await llmCallService.cleanup()
    else await logCleanupService.cleanupIncidents()
    $q.notify({ type: 'positive', message: t(`params.logs.${target}.success`) })
    cleanupTarget.value = null
  } catch (error) {
    console.error(`Failed to purge ${target} logs:`, error)
    $q.notify({ type: 'negative', message: t(`params.logs.${target}.error`) })
  } finally {
    cleanupLoading.value = false
  }
}
</script>

<style scoped>
.logs-warning {
  color: #76540f;
  border: 1px solid #f0dca6;
  background: #fffaf0;
}

.cleanup-card {
  display: flex;
  min-height: 240px;
  flex-direction: column;
  border-radius: 14px;
  background: #fff;
}

.preserved-note {
  display: flex;
  gap: 7px;
  align-items: center;
  color: #537064;
  font-size: 0.76rem;
}

.cleanup-actions {
  min-height: 58px;
  gap: 12px;
  border-top: 1px solid #edf0f5;
}

.cleanup-dialog {
  width: 520px;
  max-width: 92vw;
}

body.body--dark .logs-warning {
  color: #e8c777;
  border-color: #6b5a26;
  background: #33290f;
}

body.body--dark .cleanup-card {
  background: #1d1d1d;
}

body.body--dark .preserved-note {
  color: #9dbcae;
}

body.body--dark .cleanup-actions {
  border-top-color: #3a3f47;
}
</style>
