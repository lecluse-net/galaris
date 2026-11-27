<template>
  <tr :class="{ 'cursor-pointer': canConfigure }" @click="canConfigure && $emit('action', 'policy')">
    <td role="rowheader" class="text-left text-weight-medium">{{ account.label }}</td>
    <td v-for="period in budgetPeriods" :key="period">
      <BudgetGauge v-if="limits[period]" :envelope="limits[period]" />
    </td>
    <td v-if="showActions">
      <div class="row items-center justify-end">
        <q-btn v-if="canConfigure" dense flat round color="primary" icon="edit" :aria-label="t('inferenceBudget.edit')"
          @click.stop="$emit('action', 'policy')">
          <q-tooltip>{{ t('inferenceBudget.edit') }}</q-tooltip>
        </q-btn>
        <q-btn v-if="canManageCredits && grantablePeriods.length" dense flat round color="primary" icon="add_card" :aria-label="t('inferenceBudget.grant')"
          @click.stop="$emit('action', 'grant')">
          <q-tooltip>{{ t('inferenceBudget.grant') }}</q-tooltip>
        </q-btn>
        <BudgetCreditRequests :requests="requests" :periods="grantablePeriods" review
          @decision="(request, decision) => $emit('review', request, decision)" />
      </div>
    </td>
  </tr>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { budgetPeriods, canGrantCredit, type AccountBudget, type CreditRequest } from '../services/budgetService'
import BudgetCreditRequests from './BudgetCreditRequests.vue'
import BudgetGauge from './BudgetGauge.vue'

const props = defineProps<{ account: AccountBudget; showActions: boolean; canConfigure?: boolean; canManageCredits: boolean }>()
defineEmits<{ action: [kind: 'grant' | 'policy']; review: [request: CreditRequest, decision: 'approved' | 'rejected'] }>()
const { t } = useI18n()
const limited = computed(() => props.account.envelopes.filter(envelope => envelope.limit !== null))
const grantablePeriods = computed(() => props.account.envelopes.filter(canGrantCredit).map(envelope => envelope.period))
const limits = computed(() => Object.fromEntries(limited.value.map(envelope => [envelope.period, envelope])))
const requests = computed(() => props.canManageCredits ? props.account.requests.filter(request => request.status === 'pending') : [])
</script>
