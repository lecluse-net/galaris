<template>
  <q-page class="q-pa-md">
    <PageHeader :icon="navigationIcon('bug_report')"
      :title="t('incidents.title')"
      :description="t('incidents.description')"
    >
      <template #actions>
        <q-btn
          outline
          color="primary"
          icon="refresh"
          :label="t('incidents.refresh')"
          :loading="loading"
          @click="refresh"
        />
      </template>
    </PageHeader>

    <q-tabs v-model="tab" align="left" active-color="primary" indicator-color="primary">
      <q-tab name="incidents" icon="history" :label="t('incidents.occurrences')" />
      <q-tab name="patterns" icon="fingerprint" :label="t('incidents.patterns')" />
    </q-tabs>
    <q-separator />

    <q-tab-panels v-model="tab" animated class="bg-transparent">
      <q-tab-panel name="incidents" class="q-px-none">
        <div class="row q-col-gutter-md q-mb-md">
          <q-input
            v-model="incidentSearch"
            outlined
            dense
            clearable
            debounce="350"
            class="col-12 col-md-6"
            :label="t('incidents.search')"
            @update:model-value="reloadIncidents"
          >
            <template #prepend><q-icon name="search" /></template>
          </q-input>
          <q-select
            v-model="incidentKind"
            outlined
            dense
            clearable
            emit-value
            map-options
            class="col-6 col-md-3"
            :label="t('incidents.kind')"
            :options="kindOptions"
            @update:model-value="reloadIncidents"
          />
          <q-select
            v-model="recoveryFilter"
            outlined
            dense
            clearable
            emit-value
            map-options
            class="col-6 col-md-3"
            :label="t('incidents.recovery')"
            :options="recoveryOptions"
            @update:model-value="reloadIncidents"
          />
        </div>

        <q-banner v-if="error" rounded class="bg-red-1 text-negative q-mb-md">
          {{ error }}
        </q-banner>
        <q-table
          v-model:pagination="incidentPagination"
          flat
          bordered
          row-key="id"
          :rows="incidents"
          :columns="incidentColumns"
          :loading="loading"
          :grid="$q.screen.lt.md"
          :rows-per-page-options="rowsPerPageOptions"
          :no-data-label="t('incidents.emptyOccurrences')"
          class="incident-table"
          @request="requestIncidents"
          @row-click="openIncidentFromRow"
        >
          <template #body-cell-kind="props">
            <q-td :props="props">
              <q-chip dense square :color="kindColor(props.row.kind)" text-color="white">
                {{ kindLabel(props.row.kind) }}
              </q-chip>
            </q-td>
          </template>
          <template #body-cell-error="props">
            <q-td :props="props">
              <div class="text-weight-medium ellipsis incident-error">{{ props.row.error_message }}</div>
              <div class="text-caption text-grey-7 ellipsis">
                {{ props.row.error_type }} · {{ props.row.category }}
              </div>
            </q-td>
          </template>
          <template #body-cell-context="props">
            <q-td :props="props">
              <div>{{ contextLabel(props.row) }}</div>
              <div v-if="retryLabel(props.row)" class="text-caption text-grey-7">
                {{ retryLabel(props.row) }}
              </div>
            </q-td>
          </template>
          <template #body-cell-status="props">
            <q-td :props="props">
              <q-badge :color="statusColor(props.row.pattern_status)">
                {{ statusLabel(props.row.pattern_status) }}
              </q-badge>
              <div class="text-caption q-mt-xs">
                {{ t('incidents.occurrenceCount', { count: props.row.pattern_occurrence_count }) }}
              </div>
              <q-icon
                v-if="props.row.recovered_at"
                name="healing"
                color="positive"
                class="q-ml-xs"
                :title="t('incidents.recovered')"
              />
            </q-td>
          </template>
          <template #item="props">
            <div class="q-table__grid-item col-12">
              <q-card flat bordered class="cursor-pointer" @click="openIncident(props.row)">
                <q-card-section>
                  <div class="row items-center justify-between q-mb-sm">
                    <q-chip dense square :color="kindColor(props.row.kind)" text-color="white">
                      {{ kindLabel(props.row.kind) }}
                    </q-chip>
                    <span class="text-caption">{{ formatDate(props.row.occurred_at) }}</span>
                  </div>
                  <div class="text-weight-medium">{{ props.row.error_message }}</div>
                  <div class="text-caption text-grey-7 q-mt-xs">{{ contextLabel(props.row) }}</div>
                </q-card-section>
              </q-card>
            </div>
          </template>
        </q-table>
      </q-tab-panel>

      <q-tab-panel name="patterns" class="q-px-none">
        <div class="row q-col-gutter-md q-mb-md">
          <q-input
            v-model="patternSearch"
            outlined
            dense
            clearable
            debounce="350"
            class="col-12 col-md-6"
            :label="t('incidents.searchPatterns')"
            @update:model-value="reloadPatterns"
          >
            <template #prepend><q-icon name="search" /></template>
          </q-input>
          <q-select
            v-model="patternKind"
            outlined
            dense
            clearable
            emit-value
            map-options
            class="col-6 col-md-3"
            :label="t('incidents.kind')"
            :options="kindOptions"
            @update:model-value="reloadPatterns"
          />
          <q-select
            v-model="patternStatus"
            outlined
            dense
            clearable
            emit-value
            map-options
            class="col-6 col-md-3"
            :label="t('incidents.status')"
            :options="statusOptions"
            @update:model-value="reloadPatterns"
          />
        </div>

        <q-banner v-if="error" rounded class="bg-red-1 text-negative q-mb-md">
          {{ error }}
        </q-banner>
        <q-table
          v-model:pagination="patternPagination"
          flat
          bordered
          row-key="id"
          :rows="patterns"
          :columns="patternColumns"
          :loading="loading"
          :grid="$q.screen.lt.md"
          :rows-per-page-options="rowsPerPageOptions"
          :no-data-label="t('incidents.emptyPatterns')"
          @request="requestPatterns"
          @row-click="editPatternFromRow"
        >
          <template #body-cell-status="props">
            <q-td :props="props">
              <q-badge :color="statusColor(props.row.status)">{{ statusLabel(props.row.status) }}</q-badge>
            </q-td>
          </template>
          <template #body-cell-title="props">
            <q-td :props="props">
              <div class="text-weight-medium ellipsis incident-error">{{ props.row.title }}</div>
              <div class="text-caption text-grey-7">{{ props.row.category }}</div>
            </q-td>
          </template>
          <template #body-cell-actions="props">
            <q-td :props="props" auto-width>
              <q-btn
                v-if="canEdit"
                flat
                round
                dense
                icon="edit"
                :aria-label="t('incidents.editPattern')"
                @click.stop="editPattern(props.row)"
              />
            </q-td>
          </template>
          <template #item="props">
            <div class="q-table__grid-item col-12">
              <q-card flat bordered :class="{ 'cursor-pointer': canEdit }" @click="editPattern(props.row)">
                <q-card-section>
                  <div class="row items-center justify-between q-mb-sm">
                    <q-badge :color="statusColor(props.row.status)">{{ statusLabel(props.row.status) }}</q-badge>
                    <strong>× {{ props.row.occurrence_count }}</strong>
                  </div>
                  <div class="text-weight-medium">{{ props.row.title }}</div>
                  <div class="text-caption text-grey-7 q-mt-xs">{{ formatDate(props.row.last_seen_at) }}</div>
                </q-card-section>
              </q-card>
            </div>
          </template>
        </q-table>
      </q-tab-panel>
    </q-tab-panels>

    <q-dialog v-model="detailOpen">
      <q-card class="incident-dialog">
        <q-card-section class="galaris-dialog-title row items-center justify-between">
          <div class="col">
            <div class="text-h6">{{ t('incidents.detailTitle') }}</div>
            <div v-if="selectedIncident" class="text-caption text-grey-7">
              {{ formatDate(selectedIncident.occurred_at) }} · {{ selectedIncident.id }}
            </div>
          </div>
          <q-btn v-close-popup flat round dense icon="close" :aria-label="t('incidents.close')" />
        </q-card-section>
        <q-separator />
        <q-card-section v-if="detailLoading" class="text-center q-pa-xl"><q-spinner size="40px" /></q-card-section>
        <q-card-section v-else-if="selectedIncident" class="scroll incident-dialog__body">
          <q-banner class="bg-red-1 text-negative q-mb-md" rounded>
            <div class="text-weight-bold">{{ selectedIncident.error_type }}</div>
            <div class="pre-wrap">{{ selectedIncident.error_message }}</div>
          </q-banner>
          <div class="row q-col-gutter-md q-mb-md">
            <div class="col-12 col-md-4"><strong>{{ t('incidents.category') }}</strong><br>{{ selectedIncident.category }}</div>
            <div class="col-12 col-md-4"><strong>{{ t('incidents.phase') }}</strong><br>{{ selectedIncident.phase }}</div>
            <div class="col-12 col-md-4"><strong>{{ t('incidents.context') }}</strong><br>{{ contextLabel(selectedIncident) }}</div>
          </div>
          <q-banner v-if="selectedIncident.redacted_fields.length" rounded class="bg-orange-1 q-mb-sm">
            {{ t('incidents.redacted', { count: selectedIncident.redacted_fields.length }) }}
          </q-banner>
          <q-banner v-if="selectedIncident.truncated_fields.length" rounded class="bg-orange-1 q-mb-sm">
            {{ t('incidents.truncated', { count: selectedIncident.truncated_fields.length }) }}
          </q-banner>
          <div class="row items-center justify-between q-mb-sm">
            <div class="text-subtitle1 text-weight-bold">{{ t('incidents.fullTrace') }}</div>
            <div class="text-caption text-grey-7">{{ formatBytes(selectedIncident.trace_byte_size) }} · {{ selectedIncident.trace_content_hash }}</div>
          </div>
          <pre class="trace-view">{{ JSON.stringify(selectedIncident.trace, null, 2) }}</pre>
        </q-card-section>
      </q-card>
    </q-dialog>

    <q-dialog v-model="patternOpen">
      <q-card class="incident-dialog">
        <q-card-section class="galaris-dialog-title row items-center justify-between">
          <div class="col">
            <div class="text-h6">{{ t('incidents.patternReview') }}</div>
            <div v-if="patternForm" class="text-caption text-grey-7">{{ patternForm.title }}</div>
          </div>
          <q-btn v-close-popup flat round dense icon="close" :aria-label="t('incidents.close')" />
        </q-card-section>
        <q-separator />
        <q-card-section v-if="patternForm" class="scroll incident-dialog__body q-gutter-md">
          <q-select
            v-model="patternForm.status"
            outlined
            emit-value
            map-options
            :readonly="!canEdit"
            :label="t('incidents.status')"
            :options="statusOptions"
          />
          <q-input v-model="patternForm.diagnosis" outlined autogrow :readonly="!canEdit" :label="t('incidents.diagnosis')" />
          <q-input v-model="patternForm.root_cause" outlined autogrow :readonly="!canEdit" :label="t('incidents.rootCause')" />
          <q-input v-model="patternForm.remediation" outlined autogrow :readonly="!canEdit" :label="t('incidents.remediation')" />
          <div class="row q-col-gutter-md">
            <q-input v-model="patternForm.fixed_by_commit" outlined :readonly="!canEdit" class="col-12 col-md-6" :label="t('incidents.fixedByCommit')" />
            <q-input v-model="patternForm.regression_test" outlined :readonly="!canEdit" class="col-12 col-md-6" :label="t('incidents.regressionTest')" />
          </div>
        </q-card-section>
        <q-card-actions class="galaris-dialog-actions" v-if="canEdit" align="right">
          <q-btn flat :label="t('incidents.close')" v-close-popup />
          <q-btn color="primary" :label="t('incidents.saveReview')" :loading="saving" @click="savePattern" />
        </q-card-actions>
      </q-card>
    </q-dialog>
    <div class="q-mt-md">
      <q-btn flat color="primary" icon="arrow_back" :label="t('common.back')" to="/params" />
    </div>
  </q-page>
</template>

<script setup lang="ts">
import { navigationIcon } from '@/core/navigation'
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { useQuasar, type QTableColumn, type QTableProps } from 'quasar'
import { PageHeader, formatFileSize } from '@/core/util'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import {
  incidentService,
  type FailureIncident,
  type FailureIncidentDetail,
  type FailureKind,
  type FailurePattern,
  type FailurePatternStatus,
} from '../services/incidentService'

type TableRequest = Parameters<NonNullable<QTableProps['onRequest']>>[0]
type RecoveryFilter = 'recovered' | 'unrecovered' | null

const { t, locale } = useI18n()
const $q = useQuasar()
const router = useRouter()
const privilegeStore = usePrivilegeStore()
const canAccess = computed(() => privilegeStore.hasPrivilege(privileges.INCIDENT_ACCESS) || privilegeStore.hasPrivilege(privileges.INCIDENT_EDIT))
const canEdit = computed(() => privilegeStore.hasPrivilege(privileges.INCIDENT_EDIT))
const rowsPerPageOptions = [10, 20, 50, 100, 500]
const tab = ref<'incidents' | 'patterns'>('incidents')
const loading = ref(false)
const error = ref('')
const incidents = ref<FailureIncident[]>([])
const patterns = ref<FailurePattern[]>([])
const incidentSearch = ref('')
const patternSearch = ref('')
const incidentKind = ref<FailureKind | null>(null)
const patternKind = ref<FailureKind | null>(null)
const recoveryFilter = ref<RecoveryFilter>(null)
const patternStatus = ref<FailurePatternStatus | null>(null)
const incidentPagination = ref({ page: 1, rowsPerPage: 50, rowsNumber: 0 })
const patternPagination = ref({ page: 1, rowsPerPage: 50, rowsNumber: 0 })
const detailOpen = ref(false)
const detailLoading = ref(false)
const selectedIncident = ref<FailureIncidentDetail | null>(null)
const patternOpen = ref(false)
const patternForm = ref<FailurePattern | null>(null)
const saving = ref(false)

const kindOptions = computed(() => ([
  { label: t('incidents.kinds.llm'), value: 'llm' },
  { label: t('incidents.kinds.tool'), value: 'tool' },
]))
const recoveryOptions = computed(() => ([
  { label: t('incidents.unrecovered'), value: 'unrecovered' },
  { label: t('incidents.recovered'), value: 'recovered' },
]))
const reviewStatuses: FailurePatternStatus[] = ['new', 'triaged', 'fix_planned', 'resolved', 'ignored', 'regression']
const statusOptions = computed(() => reviewStatuses.map(status => ({
  label: statusLabel(status),
  value: status,
})))

const incidentColumns = computed<QTableColumn<FailureIncident>[]>(() => [
  { name: 'occurred_at', label: t('incidents.occurredAt'), field: 'occurred_at', format: value => formatDate(String(value)), align: 'left', sortable: false, style: 'width: 175px' },
  { name: 'kind', label: t('incidents.kind'), field: 'kind', align: 'left', style: 'width: 90px' },
  { name: 'error', label: t('incidents.error'), field: 'error_message', align: 'left' },
  { name: 'context', label: t('incidents.context'), field: row => contextLabel(row), align: 'left', classes: 'gt-sm', headerClasses: 'gt-sm', style: 'width: 220px' },
  { name: 'status', label: t('incidents.status'), field: 'pattern_status', align: 'left', style: 'width: 140px' },
])
const patternColumns = computed<QTableColumn<FailurePattern>[]>(() => [
  { name: 'last_seen_at', label: t('incidents.lastSeen'), field: 'last_seen_at', format: value => formatDate(String(value)), align: 'left', style: 'width: 175px' },
  { name: 'title', label: t('incidents.pattern'), field: 'title', align: 'left' },
  { name: 'occurrence_count', label: t('incidents.count'), field: 'occurrence_count', align: 'right', style: 'width: 90px' },
  { name: 'status', label: t('incidents.status'), field: 'status', align: 'left', style: 'width: 130px' },
  { name: 'actions', label: '', field: 'id', align: 'right', style: 'width: 48px' },
])

onMounted(async () => {
  if (!privilegeStore.loaded) await privilegeStore.loadPrivileges()
  if (!canAccess.value) {
    await router.replace('/params')
    return
  }
  await loadIncidents()
})
watch([() => privilegeStore.loaded, canAccess], ([loaded, allowed]) => {
  if (loaded && !allowed) void router.replace('/params')
})
watch(tab, value => void (value === 'incidents' ? loadIncidents() : loadPatterns()))

function refresh(): void {
  void (tab.value === 'incidents' ? loadIncidents() : loadPatterns())
}

function reloadIncidents(): void {
  incidentPagination.value.page = 1
  void loadIncidents()
}

function reloadPatterns(): void {
  patternPagination.value.page = 1
  void loadPatterns()
}

function requestIncidents(request: TableRequest): void {
  incidentPagination.value = { ...request.pagination, rowsNumber: request.pagination.rowsNumber ?? incidentPagination.value.rowsNumber }
  void loadIncidents()
}

function requestPatterns(request: TableRequest): void {
  patternPagination.value = { ...request.pagination, rowsNumber: request.pagination.rowsNumber ?? patternPagination.value.rowsNumber }
  void loadPatterns()
}

async function loadIncidents(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const response = await incidentService.listIncidents({
      page: incidentPagination.value.page,
      page_size: incidentPagination.value.rowsPerPage,
      kind: incidentKind.value || undefined,
      recovered: recoveryFilter.value === null ? undefined : recoveryFilter.value === 'recovered',
      search: (incidentSearch.value || '').trim() || undefined,
    })
    incidents.value = response.data.items
    incidentPagination.value.rowsNumber = response.data.total
  } catch {
    error.value = t('incidents.loadError')
  } finally {
    loading.value = false
  }
}

async function loadPatterns(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const response = await incidentService.listPatterns({
      page: patternPagination.value.page,
      page_size: patternPagination.value.rowsPerPage,
      kind: patternKind.value || undefined,
      status: patternStatus.value || undefined,
      search: (patternSearch.value || '').trim() || undefined,
    })
    patterns.value = response.data.items
    patternPagination.value.rowsNumber = response.data.total
  } catch {
    error.value = t('incidents.loadError')
  } finally {
    loading.value = false
  }
}

function openIncidentFromRow(_event: Event, row: FailureIncident): void {
  void openIncident(row)
}

async function openIncident(row: FailureIncident): Promise<void> {
  detailOpen.value = true
  detailLoading.value = true
  selectedIncident.value = null
  try {
    selectedIncident.value = (await incidentService.getIncident(row.id)).data
  } catch {
    detailOpen.value = false
    $q.notify({ type: 'negative', message: t('incidents.detailError') })
  } finally {
    detailLoading.value = false
  }
}

function editPatternFromRow(_event: Event, row: FailurePattern): void {
  editPattern(row)
}

function editPattern(row: FailurePattern): void {
  patternForm.value = { ...row }
  patternOpen.value = true
}

async function savePattern(): Promise<void> {
  if (!patternForm.value || !canEdit.value) return
  saving.value = true
  try {
    const updated = (await incidentService.updatePattern(patternForm.value.id, {
      status: patternForm.value.status,
      diagnosis: patternForm.value.diagnosis,
      root_cause: patternForm.value.root_cause,
      remediation: patternForm.value.remediation,
      fixed_by_commit: patternForm.value.fixed_by_commit,
      regression_test: patternForm.value.regression_test,
    })).data
    patternForm.value = updated
    patternOpen.value = false
    $q.notify({ type: 'positive', message: t('incidents.reviewSaved') })
    await loadPatterns()
  } catch {
    $q.notify({ type: 'negative', message: t('incidents.saveError') })
  } finally {
    saving.value = false
  }
}

function kindLabel(kind: FailureKind): string {
  return t(`incidents.kinds.${kind}`)
}

function kindColor(kind: FailureKind): string {
  return kind === 'tool' ? 'deep-orange' : 'purple'
}

function statusLabel(status: FailurePatternStatus): string {
  return t(`incidents.statuses.${status}`)
}

function statusColor(status: FailurePatternStatus): string {
  return ({
    new: 'negative', triaged: 'warning', fix_planned: 'info', resolved: 'positive', ignored: 'grey', regression: 'deep-orange',
  })[status]
}

function contextLabel(row: FailureIncident): string {
  if (row.tool_name) return row.tool_name
  if (row.model_code) return [row.provider_code, row.model_code].filter(Boolean).join(' / ')
  if (row.driver_code) return row.driver_code
  return row.phase
}

function retryLabel(row: FailureIncident): string {
  if (row.attempt_number === null) return ''
  if (row.retry_limit === null) return t('incidents.attempt', { attempt: row.attempt_number })
  return t('incidents.attemptOf', { attempt: row.attempt_number, limit: row.retry_limit })
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat(locale.value, { dateStyle: 'short', timeStyle: 'medium' }).format(new Date(value))
}

function formatBytes(value: number): string {
  return formatFileSize(value, locale.value)
}
</script>

<style scoped>
.incident-table :deep(tbody tr) {
  cursor: pointer;
}

.incident-error {
  max-width: min(48vw, 720px);
}

.incident-dialog {
  width: min(1100px, 96vw);
  max-width: 96vw;
}

.incident-dialog__body {
  max-height: 75vh;
}

.pre-wrap {
  white-space: pre-wrap;
}

.trace-view {
  overflow: auto;
  margin: 0;
  padding: 16px;
  border-radius: 8px;
  color: #d1d5db;
  background: #111827;
  font-size: 0.78rem;
  line-height: 1.5;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
</style>
