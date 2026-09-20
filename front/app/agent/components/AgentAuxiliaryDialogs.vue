<template>
  <q-dialog v-model="showCreateMcpToken">
    <q-card style="min-width: 400px">
      <q-card-section class="galaris-dialog-title row items-center">
        <div class="text-h6">{{ $t('agent.mcp.newToken') }}</div>
        <q-space />
        <q-btn icon="close" flat round dense v-close-popup class="text-white" :aria-label="$t('common.close')" />
      </q-card-section>
      <q-card-section>
        <q-input
          v-model="newMcpTokenLabel"
          :label="$t('agent.mcp.labelOptional')"
          outlined
          dense
          autofocus
          @keyup.enter="$emit('create-mcp-token')"
        />
      </q-card-section>
      <q-card-actions class="galaris-dialog-actions" align="right">
        <q-btn flat :label="$t('common.cancel')" color="primary" v-close-popup />
        <q-btn
          v-if="canManageMcp"
          flat
          :label="$t('common.create')"
          color="positive"
          :loading="loading"
          @click="$emit('create-mcp-token')"
        />
      </q-card-actions>
    </q-card>
  </q-dialog>

  <q-dialog v-model="showNewMcpToken">
    <q-card style="min-width: 500px">
      <q-card-section class="galaris-dialog-title row items-center">
        <div class="text-h6">{{ $t('agent.mcp.createdTitle') }}</div>
        <q-space />
        <q-btn icon="close" flat round dense v-close-popup class="text-white" :aria-label="$t('common.close')" />
      </q-card-section>
      <q-card-section>
        <p class="text-body2">{{ $t('agent.mcp.copyHint') }}</p>
        <q-input v-model="newMcpTokenValue" readonly outlined type="textarea" autogrow>
          <template #append>
            <q-btn flat round icon="content_copy" @click="$emit('copy-token', newMcpTokenValue)" />
          </template>
        </q-input>
      </q-card-section>
      <q-card-actions class="galaris-dialog-actions" align="right">
        <q-btn flat :label="$t('common.close')" color="primary" v-close-popup />
      </q-card-actions>
    </q-card>
  </q-dialog>

  <q-dialog v-model="showTitle">
    <q-card style="min-width: 400px">
      <q-card-section class="galaris-dialog-title row items-center">
        <div class="text-h6">{{ isTitleEdit ? $t('agent.editTitleDialog') : $t('agent.addTitleDialog') }}</div>
        <q-space />
        <q-btn icon="close" flat round dense v-close-popup class="text-white" :aria-label="$t('common.close')" />
      </q-card-section>
      <q-card-section class="q-pt-md">
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
          <div class="row justify-end q-mt-md q-gutter-sm">
            <q-btn :label="$t('common.cancel')" color="grey" flat v-close-popup />
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
    <q-card style="min-width: 400px">
      <q-card-section class="galaris-dialog-title row items-center">
        <div class="text-h6">{{ isGroupEdit ? $t('agent.editGroupDialog') : $t('agent.addGroupDialog') }}</div>
        <q-space />
        <q-btn icon="close" flat round dense v-close-popup class="text-white" :aria-label="$t('common.close')" />
      </q-card-section>
      <q-card-section class="q-pt-md">
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
          <div class="row justify-end q-mt-md q-gutter-sm">
            <q-btn :label="$t('common.cancel')" color="grey" flat v-close-popup />
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
    <q-card class="logs-dialog-card">
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
      <q-card-section class="logs-container q-pa-none">
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
    <q-card>
      <q-card-section class="galaris-dialog-title row items-center">
        <q-icon name="warning" size="28px" />
        <span class="q-ml-sm text-h6">{{ $t('common.deleteConfirmTitle') }}</span>
        <q-space />
        <q-btn icon="close" flat round dense v-close-popup class="text-white" :aria-label="$t('common.close')" />
      </q-card-section>
      <q-card-section>{{ deleteMessage }}</q-card-section>
      <q-card-actions class="galaris-dialog-actions" align="right">
        <q-btn flat :label="$t('common.cancel')" color="primary" v-close-popup />
        <q-btn
          v-if="canEdit"
          flat
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
import { titleLabel } from '../titleLabels'

type SelectOption = { label: string; value: string }
type TitleForm = { id: number | null; label: string; gender: 'M' | 'F' | null }
type GroupForm = { id: number | null; name: string; order: number }

defineProps<{
  canEdit: boolean
  canEditCatalog: boolean
  canManageMcp: boolean
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
  'create-mcp-token': []
  'copy-token': [value: string]
  'submit-title': []
  'submit-group': []
  'close-harness-logs': []
  'refresh-harness-logs': []
  'confirm-delete': []
}>()

const showCreateMcpToken = defineModel<boolean>('showCreateMcpToken', { required: true })
const newMcpTokenLabel = defineModel<string>('newMcpTokenLabel', { required: true })
const showNewMcpToken = defineModel<boolean>('showNewMcpToken', { required: true })
const newMcpTokenValue = defineModel<string>('newMcpTokenValue', { required: true })
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
