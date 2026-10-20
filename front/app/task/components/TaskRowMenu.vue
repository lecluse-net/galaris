<template><ActionContextMenu target=".active-task-row" :actions="actions" /></template>
<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuasar } from 'quasar'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import { showConfirmationDialog } from '@/core/util'
import { ActionContextMenu, type ContextAction } from '@/core/util'
import type { Task } from '../types'
import { useTaskStore } from '../stores/taskStore'
import { isUserPaused } from '../services/taskStatusService'
const { task } = defineProps<{ task: Task }>()
const emit = defineEmits<{ select: [id: string] }>()
const { t } = useI18n(), $q = useQuasar(), permissions = usePrivilegeStore(), store = useTaskStore()
const busy = ref(false)
async function command(action: 'run' | 'pause' | 'resume' | 'retry' | 'terminate'): Promise<void> {
  if (busy.value || !permissions.hasPrivilege(privileges.TASK_EDIT)) return
  busy.value = true
  try {
    if (action === 'run') await store.runTask(task.id)
    else if (action === 'pause') await store.pauseTask(task.id)
    else if (action === 'resume') await store.resumeTask(task.id)
    else if (action === 'retry') await store.retryTask(task.id, task.revision)
    else await store.forceTerminateTask(task.id, task.revision)
  } finally { busy.value = false }
}
function terminate(): void {
  const revision = task.revision
  showConfirmationDialog({ title: t('task.detail.forceTerminateConfirmTitle'),
    message: t('task.detail.forceTerminateConfirmMessage', { label: task.label }), cancel: true,
    ok: { label: t('task.detail.forceTerminateConfirmAction'), color: 'negative' }, focus: 'cancel',
  }).onOk(() => {
    if (task.revision !== revision) return
    void command('terminate').catch(() => $q.notify({ type: 'negative', message: t('common.anError') }))
  })
}
const actions = computed<ContextAction[]>(() => {
  const result: ContextAction[] = [{ key: 'details', icon: 'visibility', label: t('task.detailTitle'), run: () => emit('select', task.id) }]
  if (!permissions.hasPrivilege(privileges.TASK_EDIT)) return result
  const terminal = ['SUCCESS', 'ERROR'].includes(task.status)
  const executable = task.execution_expected !== false && task.coordination_type !== 'await_reply' && !task.is_coordination && !task.data?.awaiting_reply
  if (!terminal && executable) {
    if (!isUserPaused(task) && (task.status === 'CREATE' || task.paused)) result.push({ key: 'run', icon: 'play_arrow', label: t('task.detail.run'), disabled: busy.value, run: () => command('run') })
    result.push(isUserPaused(task)
      ? { key: 'resume', icon: 'play_arrow', label: t('task.detail.resume'), disabled: busy.value, run: () => command('resume') }
      : { key: 'pause', icon: 'pause', label: t('task.detail.pause'), disabled: busy.value, run: () => command('pause') })
  }
  if (task.status === 'ERROR') result.push({ key: 'retry', icon: 'replay', label: t('task.detail.retry'), disabled: busy.value, run: () => command('retry') })
  if (!terminal) result.push({ key: 'terminate', icon: 'cancel', label: t('task.detail.forceTerminate'), negative: true, separator: true, disabled: busy.value, run: terminate })
  return result
})
</script>
