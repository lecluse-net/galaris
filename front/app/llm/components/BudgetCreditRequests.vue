<template>
  <q-btn v-if="requests.length" dense flat round color="primary" icon="assignment"
    :aria-label="t('inferenceBudget.requests')" @click.stop>
    <q-tooltip>{{ t('inferenceBudget.requests') }}</q-tooltip>
    <q-menu>
      <q-list separator>
        <q-item v-for="request in requests" :key="request.id">
          <q-item-section>{{ t('inferenceBudget.requestLine', {
            period: t(`inferenceBudget.${request.period}`),
            amount: formatDollars(Number(request.amount), locale, { maximumFractionDigits: 6 }),
            status: t(`inferenceBudget.${request.status}`),
          }) }}</q-item-section>
          <q-item-section v-if="review" side>
            <div class="row q-gutter-xs">
              <q-btn v-if="periods?.includes(request.period)" v-close-popup dense color="primary"
                :label="t('inferenceBudget.approve')" @click="$emit('decision', request, 'approved')" />
              <q-btn v-close-popup dense outline color="primary" :label="t('inferenceBudget.reject')"
                @click="$emit('decision', request, 'rejected')" />
            </div>
          </q-item-section>
        </q-item>
      </q-list>
    </q-menu>
  </q-btn>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { formatDollars } from '@/core/util/facade'
import type { BudgetPeriod, CreditRequest } from '../services/budgetService'

defineProps<{ requests: CreditRequest[]; periods?: BudgetPeriod[]; review?: boolean }>()
const { t, locale } = useI18n()
defineEmits<{ decision: [request: CreditRequest, decision: 'approved' | 'rejected'] }>()
</script>
