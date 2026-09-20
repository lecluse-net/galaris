<template>
  <q-btn-dropdown
    size="sm"
    color="deep-purple"
    icon="science"
    :label="t('evaluation.capture.addToLab')"
  >
    <q-list class="capture-menu">
      <q-item
        v-for="item in captureItems"
        :key="item.target"
        v-close-popup
        :clickable="item.available"
        :disable="!item.available"
        @click="openDatasets(item.target, item.available)"
      >
        <q-item-section avatar>
          <q-icon :name="item.icon" color="deep-purple" />
        </q-item-section>
        <q-item-section>
          <q-item-label>{{ t(`evaluation.capture.${item.label}`) }}</q-item-label>
          <q-item-label caption>
            {{ t(`evaluation.capture.${item.available ? item.help : item.unavailable}`) }}
          </q-item-label>
        </q-item-section>
      </q-item>
    </q-list>
  </q-btn-dropdown>

  <LabDatasetCaptureDialog
    v-model="datasetDialog"
    :target="captureTarget"
    :source-id="taskId"
    :source-label="taskLabel"
  />
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { usePrivilegeStore } from '@/core/authorize'
import { labSectionPrivileges } from '../access'
import type { LabCaptureTarget } from '../services/mechanismEvaluationService'
import LabDatasetCaptureDialog from './LabDatasetCaptureDialog.vue'

const {
  taskId,
  taskLabel,
  hasDispatcher,
  hasBriefing,
  hasPlanner,
  hasExecutor,
} = defineProps<{
  taskId: string
  taskLabel: string
  hasDispatcher: boolean
  hasBriefing: boolean
  hasPlanner: boolean
  hasExecutor: boolean
}>()

const { t } = useI18n()
const privilegeStore = usePrivilegeStore()
const datasetDialog = ref(false)
const captureTarget = ref<LabCaptureTarget>('dispatcher')
const captureItems = computed(() => [
  { target: 'task_analysis' as const, label: 'diagnosis', help: 'diagnosisHelp', unavailable: 'diagnosisHelp', icon: 'fact_check', available: true, editPrivilege: labSectionPrivileges.tasks[1] },
  {
    target: 'dispatcher' as const,
    label: 'dispatcher',
    help: 'dispatcherHelp',
    unavailable: 'dispatcherUnavailable',
    icon: 'alt_route',
    available: hasDispatcher,
    editPrivilege: labSectionPrivileges.dispatcher[1],
  },
  {
    target: 'briefing' as const,
    label: 'briefing',
    help: 'briefingHelp',
    unavailable: 'briefingUnavailable',
    icon: 'assignment',
    available: hasBriefing,
    editPrivilege: labSectionPrivileges.briefing[1],
  },
  {
    target: 'planner' as const,
    label: 'planner',
    help: 'plannerHelp',
    unavailable: 'plannerUnavailable',
    icon: 'account_tree',
    available: hasPlanner,
    editPrivilege: labSectionPrivileges.planner[1],
  },
  {
    target: 'task_executor' as const,
    label: 'taskExecutor',
    help: 'taskExecutorHelp',
    unavailable: 'taskExecutorUnavailable',
    icon: 'smart_toy',
    available: hasExecutor,
    editPrivilege: labSectionPrivileges.task_executor[1],
  },
].filter(item => privilegeStore.hasPrivilege(item.editPrivilege)))

function openDatasets(target: LabCaptureTarget, available: boolean): void {
  if (!available) return
  captureTarget.value = target
  datasetDialog.value = true
}
</script>

<style scoped>
.capture-menu {
  width: min(310px, calc(100vw - 24px));
  min-width: 0;
  max-width: calc(100vw - 24px);
}
</style>
