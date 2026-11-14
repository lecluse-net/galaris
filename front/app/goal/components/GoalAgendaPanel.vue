<template>
  <q-dialog :model-value="true" :maximized="$q.screen.lt.md" @update:model-value="!$event && emit('close')">
    <q-card class="galaris-dialog-card goal-agenda-panel">
      <q-card-section class="galaris-dialog-title row items-center no-wrap"><q-icon name="flag" class="q-mr-sm" /><div class="text-subtitle1 ellipsis">{{ event.title }}</div><q-space /><q-btn flat round dense icon="close" :aria-label="t('common.close')" @click="emit('close')" /></q-card-section>
      <q-card-section class="q-gutter-y-md">
        <div>{{ format(event.scheduled_at) }} · {{ event.timezone }}</div>
        <q-chip color="primary" outline>{{ t(`goal.agenda.states.${event.state}`) }}</q-chip>
        <p>{{ t(event.projected ? 'goal.agenda.projectedHint' : 'goal.agenda.preservedHint') }}</p>
        <div v-if="event.sequence !== null">{{ t('goal.agenda.cycle', { number: event.sequence }) }}</div>
        <div v-if="event.started_at">{{ t('goal.agenda.started', { date: format(event.started_at) }) }}</div>
        <div v-if="event.finished_at">{{ t('goal.agenda.finished', { date: format(event.finished_at) }) }}</div>
        <div v-if="event.verdict">{{ t(`goal.verdicts.${event.verdict}`) }}</div>
        <p v-if="event.reason">{{ event.reason }}</p>
        <p v-if="!event.task_uri">{{ t('goal.agenda.noTask') }}</p>
      </q-card-section>
      <q-card-actions class="galaris-dialog-actions" align="right">
        <q-btn outline color="primary" icon="flag" :label="t('goal.agenda.openGoal')" @click="selectedResource = { kind: 'goal', id: event.goal_id, title: event.title }" />
        <q-btn v-if="event.task_uri && canReadTasks" color="primary" :label="t('goal.agenda.openTask')" @click="openTask(event.task_uri)" />
        <q-btn v-if="event.review_task_uri && canReadTasks" outline color="primary" :label="t('goal.agenda.openReview')" @click="openTask(event.review_task_uri)" />
      </q-card-actions>
    </q-card>
  </q-dialog>
  <ResourceDetailDialog v-if="selectedResource && (selectedResource.kind === 'goal' || canReadTasks)" :target="selectedResource" @close="selectedResource = null; emit('changed')" @changed="emit('changed')" />
</template>
<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuasar } from 'quasar'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import { ResourceDetailDialog, type ResourceDetailTarget } from '@/core/util'
import type { GoalAgendaEvent } from '../types'
const { event } = defineProps<{ event: GoalAgendaEvent }>()
const emit = defineEmits<{ close: []; changed: [] }>()
const { t, locale } = useI18n(), $q = useQuasar(), privilegeStore = usePrivilegeStore()
const canReadTasks = computed(() => privilegeStore.hasAnyPrivilege([privileges.TASK_ACCESS, privileges.TASK_EDIT]))
const format = (value: string) => new Intl.DateTimeFormat(locale.value, { timeZone: event.timezone, dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
const selectedResource = ref<ResourceDetailTarget | null>(null)
function openTask(uri: string): void { selectedResource.value = { kind: 'task', id: uri.slice('galaris://task/'.length), title: '' } }
</script>
<style scoped>
.goal-agenda-panel { width: 640px; max-width: 96vw; }
</style>
