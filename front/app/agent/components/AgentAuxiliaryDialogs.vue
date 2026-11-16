<template>
  <q-dialog v-model="showTitle">
    <q-card class="galaris-dialog-card" style="min-width: 400px">
      <DialogHeader :title="isTitleEdit ? $t('agent.editTitleDialog') : $t('agent.addTitleDialog')" :close-label="$t('common.close')" />
      <q-card-section class="q-pt-md galaris-dialog-body">
        <q-form class="q-gutter-md" @submit="$emit('submit-title')">
          <q-input
            :model-value="titleLabel(titleForm.label, $t)"
            @update:model-value="$emit('update-title', { label: String($event ?? '') })"
            :label="$t('agent.labelField')"
            filled
            autofocus
            :rules="[value => !!value || $t('agent.labelRule')]"
            :hint="$t('agent.labelHint')"
          />
          <q-select
            :model-value="titleForm.gender"
            @update:model-value="$emit('update-title', { gender: $event })"
            :options="genderOptions"
            :label="$t('agent.genderField')"
            filled
            emit-value
            map-options
            :rules="[value => !!value || $t('agent.genderRule')]"
          />
          <div class="galaris-dialog-actions row justify-end q-mt-md q-gutter-sm q-pa-md">
            <q-btn outline :label="$t('common.cancel')" color="grey"  v-close-popup />
            <q-btn
              v-if="canEditCatalog"
              :label="isTitleEdit ? $t('common.edit') : $t('common.create')"
              type="submit"
              color="primary"
              :loading="loading"
            />
          </div>
        </q-form>
      </q-card-section>
    </q-card>
  </q-dialog>

  <q-dialog v-model="showGroup">
    <q-card class="galaris-dialog-card" style="min-width: 400px">
      <DialogHeader :title="isGroupEdit ? $t('agent.editGroupDialog') : $t('agent.addGroupDialog')" :close-label="$t('common.close')" />
      <q-card-section class="q-pt-md galaris-dialog-body">
        <q-form class="q-gutter-md" @submit="$emit('submit-group')">
          <q-input
            :model-value="groupForm.name"
            @update:model-value="$emit('update-group', { name: String($event ?? '') })"
            :label="$t('agent.nameField')"
            filled
            autofocus
            :rules="[value => !!value || $t('agent.nameRule')]"
            :hint="$t('agent.nameHint')"
          />
          <q-input
            :model-value="groupForm.order"
            @update:model-value="$emit('update-group', { order: Number($event) })"
            :label="$t('agent.orderField')"
            type="number"
            filled
            :hint="$t('agent.orderHint')"
          />
          <div class="galaris-dialog-actions row justify-end q-mt-md q-gutter-sm q-pa-md">
            <q-btn outline :label="$t('common.cancel')" color="grey"  v-close-popup />
            <q-btn
              v-if="canEditCatalog"
              :label="isGroupEdit ? $t('common.edit') : $t('common.create')"
              type="submit"
              color="primary"
              :loading="loading"
            />
          </div>
        </q-form>
      </q-card-section>
    </q-card>
  </q-dialog>

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

  <q-dialog v-model="showDelete">
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
        <q-btn
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
import { DialogHeader } from '@/core/util'
import { titleLabel } from '../titleLabels'

type SelectOption = { label: string; value: string }
type TitleForm = { id: number | null; label: string; gender: 'M' | 'F' | null }
type GroupForm = { id: number | null; name: string; order: number }

defineProps<{
  canEdit: boolean
  canEditCatalog: boolean
  loading: boolean
  isTitleEdit: boolean
  isGroupEdit: boolean
  titleForm: TitleForm
  groupForm: GroupForm
  genderOptions: SelectOption[]
  harnessLogsAgentName: string
  harnessLogs: string[]
  harnessLogsLoading: boolean
  harnessLogColor: (line: string) => string
  deleteMessage: string
}>()

defineEmits<{
  'update-title': [value: Partial<TitleForm>]
  'update-group': [value: Partial<GroupForm>]
  'submit-title': []
  'submit-group': []
  'close-harness-logs': []
  'refresh-harness-logs': []
  'confirm-delete': []
}>()

const showTitle = defineModel<boolean>('showTitle', { required: true })
const showGroup = defineModel<boolean>('showGroup', { required: true })
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
