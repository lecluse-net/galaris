<template>
  <q-page class="mail-journal-page q-pa-md">
    <PageHeader :icon="navigationIcon('outbox')" :title="t('mailJournal.title')" :description="t('mailJournal.description')" />

    <div class="row q-col-gutter-md q-mb-lg">
      <div class="col-12 col-md-7">
        <q-input
          v-model="search"
          outlined
          dense
          clearable
          debounce="300"
          :placeholder="t('mailJournal.search')"
        >
          <template #prepend><q-icon name="search" /></template>
        </q-input>
      </div>
      <div class="col-12 col-md-4">
        <AgentSelect
          v-model="agentId"
          :options="agentOptions"
          outlined
          dense
          clearable
          emit-value
          map-options
          :label="t('mailJournal.agentFilter')"
        />
      </div>
      <div class="col-12 col-md-1 row justify-end">
        <q-btn
          flat
          round
          icon="refresh"
          color="primary"
          :loading="pendingLoading || historyLoading"
          :aria-label="t('mailJournal.refresh')"
          @click="refreshAll(false)"
        />
      </div>
    </div>

    <q-card flat bordered class="q-mb-lg">
      <q-card-section class="row items-center bg-orange-1 text-orange-10">
        <q-icon name="approval" size="sm" class="q-mr-sm" />
        <div>
          <div class="text-h6">{{ t('mailJournal.pendingTitle') }}</div>
          <div class="text-caption">{{ t('mailJournal.pendingDescription') }}</div>
        </div>
      </q-card-section>
      <q-separator />
      <q-table
        v-model:pagination="pendingPagination"
        :rows="pendingRows"
        :columns="columns"
        row-key="id"
        :loading="pendingLoading"
        :grid="$q.screen.lt.md"
        :rows-per-page-options="rowsPerPageOptions"
        :no-data-label="t('mailJournal.noPending')"
        binary-state-sort
        @request="requestPending"
        @row-click="openRow"
      >
        <template #body-cell-status="props">
          <q-td :props="props"><StatusChip :status="props.row.status" /></q-td>
        </template>
        <template #body-cell-actions="props">
          <q-td :props="props">
            <q-btn
              v-if="props.row.can_review"
              flat
              dense
              color="positive"
              icon="send"
              :label="t('mailJournal.review')"
              @click.stop="openDelivery(props.row)"
            />
            <span v-else class="text-caption text-grey-7">{{ props.row.approver_label || '—' }}</span>
          </q-td>
        </template>
      </q-table>
    </q-card>

    <q-card flat bordered>
      <q-card-section class="row items-center">
        <q-icon name="outbox" color="primary" size="sm" class="q-mr-sm" />
        <div>
          <div class="text-h6">{{ t('mailJournal.historyTitle') }}</div>
          <div class="text-caption text-grey-7">{{ t('mailJournal.historyDescription') }}</div>
        </div>
      </q-card-section>
      <q-separator />
      <q-table
        v-model:pagination="historyPagination"
        :rows="historyRows"
        :columns="columns"
        row-key="id"
        :loading="historyLoading"
        :grid="$q.screen.lt.md"
        :rows-per-page-options="rowsPerPageOptions"
        :no-data-label="t('mailJournal.noHistory')"
        binary-state-sort
        @request="requestHistory"
        @row-click="openRow"
      >
        <template #body-cell-status="props">
          <q-td :props="props"><StatusChip :status="props.row.status" /></q-td>
        </template>
        <template #body-cell-actions="props">
          <q-td :props="props">
            <q-btn flat round dense icon="visibility" :aria-label="t('mailJournal.view')" @click.stop="openDelivery(props.row)" />
          </q-td>
        </template>
      </q-table>
    </q-card>

    <q-dialog v-model="detailOpen" @hide="clearDetail">
      <q-card class="mail-detail-card">
        <q-card-section class="galaris-dialog-title row items-center no-wrap">
          <q-icon name="mail" size="sm" class="q-mr-sm" />
          <div class="text-h6 ellipsis">{{ selected?.subject || t('mailJournal.noSubject') }}</div>
          <q-space />
          <q-btn v-close-popup flat round dense icon="close" :aria-label="t('common.close')" />
        </q-card-section>
        <q-linear-progress v-if="detailLoading" indeterminate />

        <q-card-section v-if="selected" class="q-gutter-md">
          <div class="row q-col-gutter-md">
            <div class="col-12 col-sm-6"><strong>{{ t('mailJournal.agent') }}:</strong> {{ selected.agent_label }}</div>
            <div class="col-12 col-sm-6"><strong>{{ t('mailJournal.sender') }}:</strong> {{ selected.sender_address }}</div>
            <div class="col-12"><strong>{{ t('mailJournal.to') }}:</strong> {{ selected.to_addresses.join(', ') || '—' }}</div>
            <div v-if="selected.cc_addresses.length" class="col-12"><strong>{{ t('mailJournal.cc') }}:</strong> {{ selected.cc_addresses.join(', ') }}</div>
            <div v-if="selected.bcc_addresses.length" class="col-12"><strong>{{ t('mailJournal.bcc') }}:</strong> {{ selected.bcc_addresses.join(', ') }}</div>
            <div class="col-12 col-sm-6"><strong>{{ t('mailJournal.requestedAt') }}:</strong> {{ formatDate(selected.created_at) }}</div>
            <div class="col-12 col-sm-6"><strong>{{ t('mailJournal.status') }}:</strong> <StatusChip :status="selected.status" /></div>
            <div v-if="selected.approver_label" class="col-12"><strong>{{ t('mailJournal.approver') }}:</strong> {{ selected.approver_label }}</div>
            <div v-if="selected.reviewed_by_label" class="col-12"><strong>{{ t('mailJournal.reviewedBy') }}:</strong> {{ selected.reviewed_by_label }}</div>
          </div>

          <q-separator />
          <div>
            <div class="text-subtitle2 q-mb-sm">{{ t('mailJournal.body') }}</div>
            <pre class="mail-body">{{ selected.body }}</pre>
          </div>

          <div v-if="selected.attachments.length">
            <div class="text-subtitle2 q-mb-sm">{{ t('mailJournal.attachments') }}</div>
            <q-list bordered separator dense>
              <q-item v-for="(attachment, index) in selected.attachments" :key="index">
                <q-item-section avatar><q-icon name="attach_file" /></q-item-section>
                <q-item-section>
                  <q-item-label>{{ attachment.filename || t('mailJournal.attachment') }}</q-item-label>
                  <q-item-label caption>{{ attachment.media_type }} · {{ formatSize(attachment.size) }}</q-item-label>
                </q-item-section>
              </q-item>
            </q-list>
          </div>

          <q-banner v-if="selected.rejection_reason" rounded class="bg-red-1 text-negative">
            {{ t('mailJournal.rejectionReason') }}: {{ selected.rejection_reason }}
          </q-banner>

          <q-input
            v-if="selected.status === 'pending_approval' && selected.can_review"
            v-model="rejectionReason"
            type="textarea"
            outlined
            autogrow
            :label="t('mailJournal.rejectionReasonOptional')"
            maxlength="2000"
          />
        </q-card-section>

        <q-separator />
        <q-card-actions align="right" class="q-pa-md galaris-dialog-actions">
          <q-btn flat :label="t('common.close')" v-close-popup />
          <template v-if="selected?.status === 'pending_approval' && selected.can_review">
            <q-btn
              outline
              color="negative"
              icon="block"
              :label="t('mailJournal.reject')"
              :loading="reviewing === 'reject'"
              :disable="reviewing !== null"
              @click="rejectSelected"
            />
            <q-btn
              color="positive"
              icon="send"
              :label="t('mailJournal.approveAndSend')"
              :loading="reviewing === 'approve'"
              :disable="reviewing !== null"
              @click="approveSelected"
            />
          </template>
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup lang="ts">
import { navigationIcon } from '@/core/navigation'
import { computed, defineComponent, h, onMounted, ref, watch } from 'vue'
import { QChip, useQuasar, type QTableColumn } from 'quasar'
import { useI18n } from 'vue-i18n'
import { PageHeader, formatFileSize } from '@/core/util'
import { AgentSelect } from '@/app/agent'
import {
  mailService,
  type MailDeliveryDetail,
  type MailDeliveryListItem,
  type MailDeliveryStatus,
} from '../services/mailService'

const { t, locale } = useI18n()
const $q = useQuasar()
const rowsPerPageOptions = [10, 20, 50, 100, 500]
const pendingRows = ref<MailDeliveryListItem[]>([])
const historyRows = ref<MailDeliveryListItem[]>([])
const pendingLoading = ref(false)
const historyLoading = ref(false)
const search = ref('')
const agentId = ref<number | null>(null)
const agents = ref<Array<{ id: number; label: string }>>([])
const agentOptions = computed(() => agents.value.map(agent => ({ label: agent.label, value: agent.id })))
const pendingPagination = ref({ page: 1, rowsPerPage: 50, rowsNumber: 0 })
const historyPagination = ref({ page: 1, rowsPerPage: 50, rowsNumber: 0 })
const detailOpen = ref(false)
const detailLoading = ref(false)
const selected = ref<MailDeliveryDetail | null>(null)
const rejectionReason = ref('')
const reviewing = ref<'approve' | 'reject' | null>(null)

const statusColors: Record<MailDeliveryStatus, string> = {
  pending_approval: 'orange',
  claimed: 'blue-grey',
  submitting: 'blue',
  sent: 'positive',
  rejected: 'negative',
  uncertain: 'warning',
  error: 'negative',
}

const StatusChip = defineComponent({
  props: { status: { type: String, required: true } },
  setup(props) {
    return () => h(QChip, {
      dense: true,
      color: statusColors[props.status as MailDeliveryStatus] || 'grey',
      textColor: 'white',
      label: t(`mailJournal.statuses.${props.status}`),
    })
  },
})

const columns = computed<QTableColumn<MailDeliveryListItem>[]>(() => [
  { name: 'created_at', label: t('mailJournal.requestedAt'), field: 'created_at', align: 'left', format: value => formatDate(String(value)) },
  { name: 'agent', label: t('mailJournal.agent'), field: 'agent_label', align: 'left' },
  { name: 'recipients', label: t('mailJournal.recipients'), field: row => row.to_addresses.join(', '), align: 'left' },
  { name: 'subject', label: t('mailJournal.subject'), field: 'subject', align: 'left' },
  { name: 'status', label: t('mailJournal.status'), field: 'status', align: 'left' },
  { name: 'actions', label: '', field: 'id', align: 'right' },
])

function errorMessage(error: unknown): string {
  if (typeof error === 'object' && error && 'response' in error) {
    const detail = (error as { response?: { data?: { detail?: string } } }).response?.data?.detail
    if (detail) return detail
  }
  return error instanceof Error ? error.message : String(error)
}

async function loadPending(): Promise<void> {
  pendingLoading.value = true
  try {
    const page = pendingPagination.value
    const { data } = await mailService.listDeliveries({
      scope: 'pending',
      agent_id: agentId.value ?? undefined,
      search: search.value,
      offset: (page.page - 1) * page.rowsPerPage,
      limit: page.rowsPerPage,
    })
    pendingRows.value = data.items
    page.rowsNumber = data.total
  } catch (error) {
    $q.notify({ type: 'negative', message: `${t('mailJournal.loadError')}: ${errorMessage(error)}` })
  } finally {
    pendingLoading.value = false
  }
}

async function loadHistory(): Promise<void> {
  historyLoading.value = true
  try {
    const page = historyPagination.value
    const { data } = await mailService.listDeliveries({
      scope: 'history',
      agent_id: agentId.value ?? undefined,
      search: search.value,
      offset: (page.page - 1) * page.rowsPerPage,
      limit: page.rowsPerPage,
    })
    historyRows.value = data.items
    page.rowsNumber = data.total
  } catch (error) {
    $q.notify({ type: 'negative', message: `${t('mailJournal.loadError')}: ${errorMessage(error)}` })
  } finally {
    historyLoading.value = false
  }
}

async function refreshAll(resetPages: boolean): Promise<void> {
  if (resetPages) {
    pendingPagination.value.page = 1
    historyPagination.value.page = 1
  }
  await Promise.all([loadPending(), loadHistory()])
  try {
    agents.value = (await mailService.listDeliveryAgents()).data
  } catch (error) {
    $q.notify({ type: 'negative', message: `${t('mailJournal.loadError')}: ${errorMessage(error)}` })
  }
}

function requestPending(request: { pagination: { page: number; rowsPerPage: number } }): void {
  pendingPagination.value.page = request.pagination.page
  pendingPagination.value.rowsPerPage = request.pagination.rowsPerPage
  void loadPending()
}

function requestHistory(request: { pagination: { page: number; rowsPerPage: number } }): void {
  historyPagination.value.page = request.pagination.page
  historyPagination.value.rowsPerPage = request.pagination.rowsPerPage
  void loadHistory()
}

function openRow(_event: Event, row: MailDeliveryListItem): void {
  void openDelivery(row)
}

async function openDelivery(row: MailDeliveryListItem): Promise<void> {
  detailOpen.value = true
  detailLoading.value = true
  rejectionReason.value = ''
  try {
    selected.value = (await mailService.getDelivery(row.id)).data
  } catch (error) {
    detailOpen.value = false
    $q.notify({ type: 'negative', message: errorMessage(error) })
  } finally {
    detailLoading.value = false
  }
}

function clearDetail(): void {
  selected.value = null
  rejectionReason.value = ''
  reviewing.value = null
}

async function approveSelected(): Promise<void> {
  if (!selected.value) return
  reviewing.value = 'approve'
  try {
    await mailService.approveDelivery(selected.value.id)
    $q.notify({ type: 'positive', message: t('mailJournal.sentAfterApproval') })
    detailOpen.value = false
    await refreshAll(false)
  } catch (error) {
    $q.notify({ type: 'negative', message: errorMessage(error) })
  } finally {
    reviewing.value = null
  }
}

async function rejectSelected(): Promise<void> {
  if (!selected.value) return
  reviewing.value = 'reject'
  try {
    await mailService.rejectDelivery(selected.value.id, rejectionReason.value)
    $q.notify({ type: 'positive', message: t('mailJournal.rejectedConfirmation') })
    detailOpen.value = false
    await refreshAll(false)
  } catch (error) {
    $q.notify({ type: 'negative', message: errorMessage(error) })
  } finally {
    reviewing.value = null
  }
}

function formatDate(value: string | null): string {
  if (!value) return '—'
  return new Intl.DateTimeFormat(locale.value, { dateStyle: 'short', timeStyle: 'short' }).format(new Date(value))
}

function formatSize(value: number | undefined): string {
  if (value === undefined) return '—'
  return formatFileSize(value, locale.value)
}

watch([search, agentId], () => { void refreshAll(true) })
onMounted(() => { void refreshAll(false) })
</script>

<style scoped>
.mail-detail-card {
  width: min(900px, 95vw);
  max-width: 900px;
  max-height: 90vh;
  overflow-y: auto;
}

.mail-body {
  margin: 0;
  padding: 16px;
  border-radius: 4px;
  background: #f5f5f5;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font: inherit;
}

@media (max-width: 1023px) {
  .mail-journal-page {
    padding: 12px;
  }
}
</style>
