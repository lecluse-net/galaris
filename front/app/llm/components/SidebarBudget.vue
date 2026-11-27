<template>
  <div v-if="displayed.length" class="sidebar-budget">
    <BudgetGauge v-for="envelope in displayed" :key="envelope.period" :envelope="envelope" compact />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useAuthStore } from '@/core/user'
import { startVisiblePolling } from '@/core/util/facade'
import { budgetChanged, budgetService, type Envelope } from '../services/budgetService'
import BudgetGauge from './BudgetGauge.vue'

const auth = useAuthStore()
const envelopes = ref<Envelope[]>([])
const displayed = computed(() => envelopes.value.filter(item => item.limit !== null))
let controller: AbortController | undefined
let stopPolling: (() => void) | undefined

async function refresh() {
  controller?.abort()
  const user = auth.user?.id
  if (!auth.isAuthenticated || user === undefined) return
  const current = new AbortController()
  controller = current
  try {
    const snapshot = await budgetService.me(current.signal)
    if (!current.signal.aborted && auth.user?.id === user) envelopes.value = snapshot.account.envelopes
  } catch {
    // A background refresh must not interrupt the current page.
  }
}

function refreshOnBudgetChange(): void {
  void refresh()
}

watch(() => auth.user?.id, () => { envelopes.value = []; void refresh() })
onMounted(() => {
  void refresh()
  stopPolling = startVisiblePolling(refresh, 30_000)
  window.addEventListener(budgetChanged, refreshOnBudgetChange)
})
onUnmounted(() => {
  controller?.abort()
  stopPolling?.()
  window.removeEventListener(budgetChanged, refreshOnBudgetChange)
})
</script>

<style scoped>
.sidebar-budget {
  display: grid;
  grid-template-columns: max-content minmax(0, 1fr) max-content;
  column-gap: 4px;
  margin-block-start: 10px;
  padding: 2px 10px;
  container: sidebar-budget / inline-size;
}
</style>
