<template>
  <q-dialog v-model="showHarnessLogs" @hide="$emit('close-harness-logs')">
    <q-card class="logs-dialog-card galaris-dialog-card">
      <q-card-section class="galaris-dialog-title row items-center">
        <div class="text-h6">{{ $t('agent.harness.logsTitle') }} — {{ harnessLogsAgentName }}</div>
        <q-space />
        <q-btn
          icon="refresh"
          flat
          round
          dense
          class="text-white"
          :loading="harnessLogsLoading"
          :aria-label="$t('common.refresh')"
          @click="$emit('refresh-harness-logs')"
        />
        <q-btn icon="close" flat round dense class="text-white" :aria-label="$t('common.close')" v-close-popup />
      </q-card-section>
      <q-card-section class="logs-container q-pa-none galaris-dialog-body">
        <div v-if="!harnessLogs.length" class="text-grey-5 q-pa-md">
          {{ $t('agent.harness.logsEmpty') }}
        </div>
        <div
          v-for="(line, index) in harnessLogs"
          :key="index"
          class="log-line q-px-sm"
          :style="{ color: harnessLogColor(line) }"
        >
          {{ line }}
        </div>
      </q-card-section>
    </q-card>
  </q-dialog>

  <q-dialog data-confirmation v-model="showDelete">
    <q-card class="galaris-dialog-card">
      <q-card-section class="galaris-dialog-title row items-center">
        <q-icon name="warning" size="28px" />
        <span class="q-ml-sm text-h6">{{ $t('common.deleteConfirmTitle') }}</span>
        <q-space />
        <q-btn icon="close" flat round dense v-close-popup class="text-white" :aria-label="$t('common.close')" />
      </q-card-section>
      <q-card-section class="galaris-dialog-body">{{ deleteMessage }}</q-card-section>
      <q-card-actions class="galaris-dialog-actions" align="right">
        <q-btn outline  :label="$t('common.cancel')" color="primary" v-close-popup />
        <q-btn data-autofocus
          v-if="canEdit"

          :label="$t('common.delete')"
          color="negative"
          v-close-popup
          @click="$emit('confirm-delete')"
        />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
defineProps<{
  canEdit: boolean
  harnessLogsAgentName: string
  harnessLogs: string[]
  harnessLogsLoading: boolean
  harnessLogColor: (line: string) => string
  deleteMessage: string
}>()

defineEmits<{
  'close-harness-logs': []
  'refresh-harness-logs': []
  'confirm-delete': []
}>()

const showHarnessLogs = defineModel<boolean>('showHarnessLogs', { required: true })
const showDelete = defineModel<boolean>('showDelete', { required: true })
</script>

<style scoped>
.log-line {
  white-space: pre-wrap;
  word-break: break-all;
  line-height: 1.5;
}

.logs-container {
  height: 70vh;
  overflow-y: auto;
  background: #1e1e1e;
  font-family: monospace;
  font-size: 12px;
  padding: 12px;
}

.logs-dialog-card {
  width: 1400px;
  max-width: 97vw;
}
</style>
