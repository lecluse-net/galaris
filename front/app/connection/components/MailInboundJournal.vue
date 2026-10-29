<template>
  <div>
    <q-banner role="status" class="q-mb-md">{{ t('mailJournal.inboundPolicy') }}</q-banner>
    <div class="row q-col-gutter-md q-mb-md">
      <div class="col-12 col-md-7">
        <q-input v-model="search" outlined dense clearable debounce="300" :label="t('mailJournal.inboundSearch')" />
      </div>
      <div class="col-10 col-md-4">
        <AgentSelect v-model="agentId" :options="agentOptions" outlined dense clearable emit-value map-options :label="t('mailJournal.agentFilter')" />
      </div>
      <div class="col-2 col-md-1">
        <q-btn flat round icon="refresh" :aria-label="t('mailJournal.refresh')" :loading="loading" @click="load" />
      </div>
    </div>
    <q-banner v-if="error" role="alert" class="q-mb-md">
      {{ t('mailJournal.loadError') }}
      <template #action><q-btn outline :label="t('permissions.retry')" @click="load" /></template>
    </q-banner>
    <q-table v-model:pagination="pagination" :rows="rows" :columns="columns" row-key="id"
      :loading="loading" :grid="$q.screen.lt.md" wrap-cells
      :rows-per-page-options="[10, 20, 50, 100, 500]" :no-data-label="t('mailJournal.noHistory')"
      @request="requestPage" @row-click="(_event, row) => open(row.id)">
      <template #body-cell-status="props">
        <q-td :props="props">{{ statusLabel(props.row) }}</q-td>
      </template>
      <template #body-cell-actions="props"><q-td :props="props">
        <q-btn flat round icon="visibility" :aria-label="t('mailJournal.view')" @click.stop="open(props.row.id)" />
      </q-td></template>
      <template #item="props">
        <div class="col-12 q-pa-xs"><q-card flat bordered>
          <q-card-section>
            <div class="text-subtitle1">{{ props.row.subject || t('mailJournal.noSubject') }}</div>
            <div>{{ props.row.sender_address }} · {{ props.row.agent_label }}</div>
            <div>{{ date(props.row.created_at) }} · {{ statusLabel(props.row) }}</div>
          </q-card-section>
          <q-card-actions><q-btn outline :label="t('mailJournal.view')" @click="open(props.row.id)" /></q-card-actions>
        </q-card></div>
      </template>
    </q-table>
    <q-dialog v-model="detailOpen" @hide="closeDetail">
      <q-card class="inbound-detail galaris-dialog-card">
        <q-card-section class="galaris-dialog-title row items-center no-wrap">
          <div class="text-h6 ellipsis">{{ detail?.subject || t('mailJournal.inboundTab') }}</div>
          <q-space /><q-btn v-close-popup flat round dense icon="close" :aria-label="t('common.close')" />
        </q-card-section>
        <q-linear-progress v-if="detailLoading" indeterminate />
        <q-card-section v-if="detail" class="galaris-dialog-body">
          <dl>
            <dt>{{ t('mailJournal.agent') }}</dt><dd>{{ detail.agent_label }}</dd>
            <dt>{{ t('mailJournal.sender') }}</dt><dd>{{ detail.sender_address }}</dd>
            <dt>{{ t('mailJournal.to') }}</dt><dd>{{ detail.to_addresses.join(', ') }}</dd>
            <dt>{{ t('mailJournal.status') }}</dt><dd>{{ statusLabel(detail) }}</dd>
            <dt>{{ t('mailJournal.contact') }}</dt><dd>{{ t(detail.known_contact ? 'mailJournal.knownContact' : 'mailJournal.unknownContact') }}</dd>
            <dt>{{ t('mailJournal.receivedAt') }}</dt><dd>{{ date(detail.created_at) }}</dd>
            <dt>{{ t('mailJournal.authorizedAt') }}</dt><dd>{{ date(detail.authorized_at) }}</dd>
            <dt>{{ t('mailJournal.readAt') }}</dt><dd>{{ date(detail.read_at) }}</dd>
            <dt>{{ t('mailJournal.admittedAt') }}</dt><dd>{{ date(detail.admitted_at) }}</dd>
          </dl>
          <q-banner v-if="detail.error">{{ detail.error }}</q-banner>
          <template v-if="detail.content">
            <div class="text-subtitle2">{{ t('mailJournal.body') }}</div>
            <pre class="inbound-body">{{ detail.content.body }}</pre>
            <p v-if="(detail.content.body_total ?? 0) > (detail.content.body_end ?? 0)">{{ t('mailJournal.bodyTruncated') }}</p>
            <q-list v-if="detail.content.attachments?.length" bordered>
              <q-item v-for="(attachment, index) in detail.content.attachments" :key="index">
                <q-item-section avatar><q-icon name="attach_file" /></q-item-section>
                <q-item-section>{{ attachment.filename }}</q-item-section>
              </q-item>
            </q-list>
          </template>
          <q-banner v-else role="status">{{ t('mailJournal.bodyUnread') }}</q-banner>
          <p v-if="authorization?.can_remember">{{ t('mailJournal.alwaysProcessExplanation') }}</p>
        </q-card-section>
        <q-card-section v-if="detailError" role="alert">{{ t('mailJournal.loadError') }}</q-card-section>
        <q-card-actions align="right" class="galaris-dialog-actions">
          <q-btn v-close-popup outline :label="t('common.close')" />
          <template v-if="authorization?.can_answer && canEdit">
            <q-btn color="negative" :label="t('permissions.denyAction')" :disable="answering" @click="answer(false)" />
            <q-btn color="primary" :label="t('mailJournal.allowProcessing')" :disable="answering" @click="answer(true)" />
            <q-btn v-if="authorization.can_remember" outline color="primary" :label="t('mailJournal.alwaysProcess')" :disable="answering" @click="answer(true, true)" />
            <q-btn v-if="authorization.can_remember" color="negative" :label="t('mailJournal.neverProcess')" :disable="answering" @click="answer(false, true)" />
          </template>
        </q-card-actions>
      </q-card>
    </q-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useQuasar, type QTableColumn } from 'quasar'
import { useI18n } from 'vue-i18n'
import { AgentSelect } from '@/app/agent'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import { mailService, type MailInboundItem, type MailInboundDetail } from '../services/mailService'
import { answerActionAuthorization, getActionAuthorization, type ActionAuthorization } from '../services/permissionService'

const { agents } = defineProps<{ agents: Array<{ id: number; label: string }> }>()
const { t, locale } = useI18n()
const $q = useQuasar()
const privilegeStore = usePrivilegeStore()
const canEdit = computed(() => privilegeStore.hasPrivilege(privileges.CONNECTION_EDIT))
const search = ref('')
const agentId = ref<number | null>(null)
const agentOptions = computed(() => agents.map(agent => ({ label: agent.label, value: agent.id })))
const rows = ref<MailInboundItem[]>([])
const loading = ref(false)
const error = ref(false)
const pagination = ref({ page: 1, rowsPerPage: 50, rowsNumber: 0 })
const detailOpen = ref(false)
const detail = ref<MailInboundDetail | null>(null)
const authorization = ref<ActionAuthorization | null>(null)
const detailLoading = ref(false)
const detailError = ref(false)
const answering = ref(false)
let listController: AbortController | undefined
let detailController: AbortController | undefined
let listGeneration = 0
let detailGeneration = 0
let disposed = false
const columns = computed<QTableColumn<MailInboundItem>[]>(() => [
  { name: 'date', label: t('mailJournal.receivedAt'), field: 'created_at', format: date, align: 'left' },
  { name: 'agent', label: t('mailJournal.agent'), field: 'agent_label', align: 'left' },
  { name: 'sender', label: t('mailJournal.sender'), field: 'sender_address', align: 'left' },
  { name: 'subject', label: t('mailJournal.subject'), field: 'subject', align: 'left' },
  { name: 'status', label: t('mailJournal.status'), field: 'status', align: 'left' },
  { name: 'actions', label: '', field: 'id', align: 'right' },
])
function date(value: string | null): string {
  return value ? new Intl.DateTimeFormat(locale.value, { dateStyle: 'short', timeStyle: 'short' }).format(new Date(value)) : '—'
}
function statusLabel(row: MailInboundItem): string {
  if (row.status === 'pending_approval' && row.authorization_status === 'approved') return t('mailJournal.inboundStatuses.authorized')
  return t(`mailJournal.inboundStatuses.${row.status}`)
}
async function load(): Promise<void> {
  listController?.abort()
  listController = new AbortController()
  const generation = ++listGeneration
  loading.value = true
  error.value = false
  try {
    const result = (await mailService.listInbound({ agent_id: agentId.value ?? undefined, search: search.value ?? '',
      offset: (pagination.value.page - 1) * pagination.value.rowsPerPage, limit: pagination.value.rowsPerPage }, listController.signal)).data
    if (generation !== listGeneration || disposed) return
    rows.value = result.items
    pagination.value.rowsNumber = result.total
  } catch { if (generation === listGeneration && !disposed) error.value = true }
  finally { if (generation === listGeneration && !disposed) loading.value = false }
}
function requestPage(request: { pagination: { page: number; rowsPerPage: number } }): void {
  pagination.value.page = request.pagination.page
  pagination.value.rowsPerPage = request.pagination.rowsPerPage
  void load()
}
async function open(id: string): Promise<void> {
  closeDetail()
  detailOpen.value = true
  detailLoading.value = true
  detailController = new AbortController()
  const generation = ++detailGeneration
  try {
    const result = (await mailService.getInbound(id, detailController.signal)).data
    if (generation !== detailGeneration || disposed) return
    detail.value = result
    if (result.can_review && result.authorization_id && canEdit.value) {
      const decision = await getActionAuthorization(result.authorization_id, detailController.signal)
      if (generation === detailGeneration && !disposed) authorization.value = decision
    }
  } catch { if (generation === detailGeneration && !disposed) detailError.value = true }
  finally { if (generation === detailGeneration && !disposed) detailLoading.value = false }
}
function closeDetail(): void {
  detailController?.abort()
  detailGeneration++
  detail.value = null
  authorization.value = null
  detailError.value = false
}
async function answer(approved: boolean, remember = false): Promise<void> {
  const id = authorization.value?.id
  if (!id || answering.value) return
  const generation = detailGeneration
  answering.value = true
  try {
    await answerActionAuthorization(id, approved, remember)
    if (disposed) return
    $q.notify({ type: 'positive', message: t('mailJournal.processingDecisionRecorded') })
    // The decision belongs to the original receipt, even if another is now open.
    if (generation === detailGeneration) detailOpen.value = false
    await load()
  } catch { if (!disposed) $q.notify({ type: 'negative', message: t('permissions.error') }) }
  finally { answering.value = false }
}
watch([search, agentId], () => { pagination.value.page = 1; void load() })
onMounted(() => { void load() })
onBeforeUnmount(() => { disposed = true; listGeneration++; listController?.abort(); closeDetail() })
</script>

<style scoped>
.inbound-detail { width: 850px; max-width: 95vw; overflow-wrap: anywhere; }
dl { display: grid; grid-template-columns: auto 1fr; gap: 8px 16px; }
dt { font-weight: 600; }
dd { margin: 0; min-width: 0; }
.inbound-body { white-space: pre-wrap; overflow-wrap: anywhere; font: inherit; }
@media (max-width: 599px) { dl { display: block; } dd { margin-bottom: 12px; } }
</style>
