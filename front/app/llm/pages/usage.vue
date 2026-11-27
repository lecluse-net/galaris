<route lang="json">
{ "meta": { "requiresAuth": true } }
</route>

<template>
  <q-page class="q-pa-md">
    <PageHeader icon="speed" :title="t('inferenceBudget.title')" :description="t('inferenceBudget.description')" />
    <q-linear-progress v-if="loading" indeterminate :aria-label="t('inferenceBudget.loading')" />
    <q-banner v-if="failed" rounded class="q-mb-md">
      {{ t('inferenceBudget.failed') }}
      <template #action><q-btn color="primary" :label="t('inferenceBudget.retry')" @click="load" /></template>
    </q-banner>
    <q-banner v-if="reviewError" role="alert" class="q-mb-md text-negative">{{ reviewError }}</q-banner>
    <q-card v-if="overview" flat bordered class="q-mb-md">
      <q-card-section>
        <h2 class="text-h6 q-my-none">{{ t('inferenceBudget.mine') }}</h2>
        <div v-if="overview.can_configure_own || canRequestCredit || overview.account.requests.length"
          class="row items-center q-gutter-sm q-mt-xs">
          <q-btn v-if="overview.can_configure_own" color="primary" :label="t('inferenceBudget.editOwn')"
            @click="open('policy', overview.account)" />
          <q-btn v-if="canRequestCredit" color="primary" :label="t('inferenceBudget.request')"
            @click="open('request', overview.account)" />
          <BudgetCreditRequests :requests="overview.account.requests" />
        </div>
      </q-card-section>
      <q-card-section v-if="ownLimits.length" class="own-limits q-pt-none">
        <div v-for="limit in ownLimits" :key="limit.period">
          <strong>{{ t(`inferenceBudget.${limit.period}`) }}</strong>
          <BudgetGauge :envelope="limit" />
        </div>
        <p v-if="!canRequestCredit" class="text-caption q-mb-none">{{ t('inferenceBudget.noTeamManager') }}</p>
      </q-card-section>
    </q-card>
    <q-table v-if="managed.length || pagination.rowsNumber" v-model:pagination="pagination"
      :rows="managed" :columns="columns" row-key="user_id" flat bordered wrap-cells separator="cell"
      :rows-per-page-options="[10, 20, 50, 100, 500]" @request="requestPage">
      <template #body="{ row }">
        <BudgetAccount :account="row"
          :can-configure="row.can_configure" :can-manage-credits="row.can_manage_credits"
          :show-actions="showAccountActions"
          @action="open($event, row)" @review="reviewRequest" />
      </template>
    </q-table>
    <q-dialog :model-value="dialog !== null" aria-labelledby="inference-budget-dialog-title"
      @update:model-value="value => { if (!value) close() }">
      <q-card v-if="dialog" class="galaris-dialog-card" style="width: 460px; max-width: 92vw">
        <DialogHeader :title="t(`inferenceBudget.${dialogTitle}`)" title-id="inference-budget-dialog-title" />
        <q-form class="galaris-dialog-form" @submit="submit">
          <q-card-section class="galaris-dialog-body column q-gutter-y-md">
            <div v-if="dialog.kind !== 'request'" class="text-subtitle2">{{ dialog.account.label }}</div>
            <template v-if="dialog.kind === 'policy'">
              <q-input v-for="key in budgetPeriods" :key="key" v-model="limits[key]" type="number" outlined min="0"
                step="0.01" suffix="$" class="budget-limit-input" :label="t(`inferenceBudget.${key}`)"
                @keydown.down.prevent="stepLimit(key, -1)" @keydown.up.prevent="stepLimit(key, 1)">
                <template #append>
                  <q-btn flat round dense color="primary" icon="remove" :disable="Number(limits[key]) < 1"
                    :aria-label="t('inferenceBudget.decreaseLimit', { period: t(`inferenceBudget.${key}`) })"
                    @click="stepLimit(key, -1)" />
                  <q-btn flat round dense color="primary" icon="add"
                    :aria-label="t('inferenceBudget.increaseLimit', { period: t(`inferenceBudget.${key}`) })"
                    @click="stepLimit(key, 1)" />
                </template>
              </q-input>
              <div class="text-caption">{{ t('inferenceBudget.blankUnlimited') }}</div>
            </template>
            <template v-else-if="dialog.kind === 'request' || dialog.kind === 'grant'">
              <q-select v-model="period" outlined :options="periodChoices" emit-value map-options :label="t('inferenceBudget.period')" />
              <q-input v-model="amount" outlined type="number" min="0.000001" step="0.000001" :label="t('inferenceBudget.dollars')" />
            </template>
            <q-banner v-if="actionError" role="alert" class="text-negative">{{ actionError }}</q-banner>
          </q-card-section>
          <q-separator />
          <q-card-actions align="right" class="galaris-dialog-actions">
            <q-btn v-close-popup outline color="primary" :label="t('inferenceBudget.cancel')" />
            <q-btn color="primary" type="submit" :loading="saving" :disable="!canSubmit" :label="t('inferenceBudget.save')" />
          </q-card-actions>
        </q-form>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { QTableColumn } from 'quasar'
import { apiErrorDetail, isCancelledRequest } from '@/core/api'
import { useAuthStore } from '@/core/user'
import { DialogHeader, PageHeader } from '@/core/util'
import { startVisiblePolling } from '@/core/util/facade'
import BudgetAccount from '../components/BudgetAccount.vue'
import BudgetCreditRequests from '../components/BudgetCreditRequests.vue'
import BudgetGauge from '../components/BudgetGauge.vue'
import { budgetChanged, budgetPeriods, budgetService, canGrantCredit, type AccountBudget, type BudgetPeriod, type CreditRequest, type ManagedAccountBudget } from '../services/budgetService'

type Kind = 'grant' | 'request' | 'policy'
interface DialogState { kind: Kind; account: AccountBudget; operationId: string }
const { t } = useI18n()
const limitInputFormat = new Intl.NumberFormat('en-US', {
  useGrouping: false, minimumFractionDigits: 2, maximumFractionDigits: 2,
})
const auth = useAuthStore()
const overview = ref<Awaited<ReturnType<typeof budgetService.me>>>()
const managed = ref<ManagedAccountBudget[]>([])
const pagination = ref({ page: 1, rowsPerPage: 50, rowsNumber: 0 })
const loading = ref(false)
const failed = ref(false)
let controller: AbortController | undefined
let stopPolling: (() => void) | undefined
const dialog = ref<DialogState | null>(null)
const period = ref<BudgetPeriod>('session')
const amount = ref('')
const limits = ref<Record<BudgetPeriod, string>>({ session: '', weekly: '', monthly: '' })
const saving = ref(false)
const actionError = ref('')
const reviewing = ref(false)
const reviewError = ref('')
const ownLimits = computed(() => overview.value?.account.envelopes.filter(envelope => envelope.limit !== null) ?? [])
const canRequestCredit = computed(() => ownLimits.value.length > 0 && overview.value?.can_request_credit)
const showAccountActions = computed(() => managed.value.some(account => account.can_configure || (
  account.can_manage_credits && (account.envelopes.some(canGrantCredit) || account.requests.some(request => request.status === 'pending'))
)))
const columns = computed<QTableColumn<AccountBudget>[]>(() => {
  const result: QTableColumn<AccountBudget>[] = [
    { name: 'label', field: 'label', label: t('inferenceBudget.account'), align: 'left' },
    ...budgetPeriods.map(period => ({
      name: period, field: 'envelopes' as const, label: t(`inferenceBudget.${period}`), align: 'left' as const,
    })),
  ]
  if (showAccountActions.value) {
    result.push({ name: 'actions', field: 'user_id', label: t('common.actions'), align: 'right' })
  }
  return result
})
const dialogTitle = computed(() => {
  const kind = dialog.value?.kind
  return kind === 'policy' ? 'edit' : kind ?? 'save'
})
const periodChoices = computed(() => (dialog.value?.account.envelopes ?? [])
  .filter(e => dialog.value?.kind === 'grant' ? canGrantCredit(e) : e.limit !== null)
  .map(e => ({ value: e.period, label: t(`inferenceBudget.${e.period}`) })))
const canSubmit = computed(() => {
  const kind = dialog.value?.kind
  if (kind === 'request' || kind === 'grant') return Number(amount.value) > 0 && periodChoices.value.some(p => p.value === period.value)
  return kind === 'policy'
})

async function load() {
  controller?.abort()
  const user = auth.user?.id
  if (user === undefined) return
  const current = new AbortController()
  controller = current
  loading.value = overview.value === undefined
  try {
    const [own, others] = await Promise.allSettled([
      budgetService.me(current.signal),
      budgetService.managed(pagination.value.page, pagination.value.rowsPerPage, current.signal),
    ])
    if (current.signal.aborted || auth.user?.id !== user) return
    if (own.status === 'fulfilled') overview.value = own.value
    managed.value = others.status === 'fulfilled' ? others.value.items : []
    pagination.value.rowsNumber = others.status === 'fulfilled' ? others.value.total : 0
    failed.value = own.status === 'rejected' || others.status === 'rejected'
  } finally {
    if (!current.signal.aborted) loading.value = false
  }
}

function requestPage({ pagination: next }: { pagination: { page: number; rowsPerPage: number } }) {
  pagination.value = { ...pagination.value, page: next.page, rowsPerPage: next.rowsPerPage }
  void load()
}

function limitInputValue(limit: string | null): string {
  return limit === null ? '' : limitInputFormat.format(Number(limit))
}

function stepLimit(period: BudgetPeriod, direction: -1 | 1) {
  const amount = Number(limits.value[period])
  if (Number.isFinite(amount) && amount + direction >= 0) {
    limits.value[period] = limitInputFormat.format(amount + direction)
  }
}

function editedLimits(account: AccountBudget): Record<BudgetPeriod, string | null> {
  const values = { session: limits.value.session || null, weekly: limits.value.weekly || null, monthly: limits.value.monthly || null }
  for (const { period, limit } of account.envelopes) {
    if (limits.value[period] === limitInputValue(limit)) values[period] = limit
  }
  return values
}

function open(kind: Kind, account: AccountBudget) {
  limits.value = { session: '', weekly: '', monthly: '' }
  for (const { period, limit } of account.envelopes) limits.value[period] = limitInputValue(limit)
  period.value = account.envelopes.find(e => kind === 'grant' ? canGrantCredit(e) : e.limit !== null)?.period ?? 'session'
  amount.value = ''
  actionError.value = ''
  dialog.value = { kind, account, operationId: kind === 'grant' ? crypto.randomUUID() : '' }
}

function close() {
  dialog.value = null
}

function refreshAfterChange() {
  window.dispatchEvent(new Event(budgetChanged))
  return load()
}

async function reviewRequest(request: CreditRequest, decision: 'approved' | 'rejected') {
  if (reviewing.value) return
  reviewing.value = true
  reviewError.value = ''
  try {
    await budgetService.review(request.id, decision)
    await refreshAfterChange()
  } catch (error) {
    if (!isCancelledRequest(error)) reviewError.value = apiErrorDetail(error) ?? t('inferenceBudget.actionFailed')
  } finally {
    reviewing.value = false
  }
}

async function submit() {
  const current = dialog.value
  if (!current || !canSubmit.value || saving.value) return
  saving.value = true
  actionError.value = ''
  try {
    if (current.kind === 'request') await budgetService.request(period.value, amount.value)
    else if (current.kind === 'grant') await budgetService.grant(current.account.user_id, period.value, amount.value, current.operationId)
    else await budgetService.policy(current.account.user_id, editedLimits(current.account))
    if (dialog.value === current) close()
    await refreshAfterChange()
  } catch (error) {
    if (dialog.value === current) actionError.value = apiErrorDetail(error) ?? t('inferenceBudget.actionFailed')
  } finally {
    saving.value = false
  }
}

watch(() => auth.user?.id, () => {
  close()
  reviewError.value = ''
  overview.value = undefined
  managed.value = []
  pagination.value = { page: 1, rowsPerPage: 50, rowsNumber: 0 }
  void load()
})
onMounted(() => {
  void load()
  stopPolling = startVisiblePolling(() => dialog.value ? undefined : load(), 30_000)
})
onUnmounted(() => { controller?.abort(); stopPolling?.() })
</script>

<style scoped>
.own-limits {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 12rem), 1fr));
  gap: 12px 20px;
}
.own-limits > p { grid-column: 1 / -1; }
.budget-limit-input :deep(input[type="number"]) { appearance: textfield; }
.budget-limit-input :deep(input::-webkit-inner-spin-button) { appearance: none; margin: 0; }
</style>
