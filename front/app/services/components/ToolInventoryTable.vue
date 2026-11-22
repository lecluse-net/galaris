<template>
  <q-table class="inventory-table" flat dense wrap-cells
    :aria-label="serviceLabel"
    :rows="tools" :columns="columns" row-key="name"
    :pagination="{ rowsPerPage: 50 }" :rows-per-page-options="[10, 20, 50, 100, 500]"
    :hide-bottom="tools.length <= 10">
    <template #body-cell-name="slot">
      <q-td :props="slot">
        <code class="tool-name">{{ slot.row.name }}</code>
      </q-td>
    </template>
    <template #body-cell-conversation="slot">
      <q-td :props="slot">
        <StatusBadge :tone="slot.row.conversation_enabled ? 'success' : 'neutral'"
          :label="t(slot.row.conversation_enabled ? 'toolInventory.open' : 'toolInventory.closed')" />
      </q-td>
    </template>
    <template #body-cell-authorization="slot">
      <q-td :props="slot">
        <StatusBadge :tone="tones[slot.row.default_state as InventoryToolState]"
          :label="t(`toolInventory.states.${slot.row.default_state}`)" />
        <div v-if="slot.row.service_override" class="text-caption q-mt-xs">
          {{ t('toolInventory.serviceOverride', { state: t(`toolInventory.states.${slot.row.service_override}`) }) }}
        </div>
      </q-td>
    </template>
  </q-table>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { QTableColumn } from 'quasar'
import { StatusBadge, type StatusBadgeTone } from '@/core/util'
import type { InventoryTool, InventoryToolState } from '../services/serviceApi'

defineProps<{ serviceLabel: string; tools: InventoryTool[] }>()
const { t } = useI18n()
const tones: Record<InventoryToolState, StatusBadgeTone> = {
  enabled: 'success', ask: 'warning', disabled: 'error',
}
const columns = computed<QTableColumn<InventoryTool>[]>(() => [
  { name: 'name', label: t('services.conversationTools.tool'), field: 'name', align: 'left', sortable: true },
  { name: 'conversation', label: t('toolInventory.conversation'), field: 'conversation_enabled', align: 'left', sortable: true },
  { name: 'authorization', label: t('toolInventory.authorization'), field: 'default_state', align: 'left', sortable: true },
])

</script>

<style scoped>
.tool-name {
  overflow-wrap: anywhere;
}

.inventory-table :deep(table) {
  table-layout: fixed;
}

.inventory-table :deep(th:first-child) {
  width: 47%;
}

.inventory-table :deep(th) {
  white-space: normal;
}

@media (max-width: 1023px) {
  .inventory-table :deep(th),
  .inventory-table :deep(td) {
    padding-inline: 8px;
  }

  .inventory-table :deep(th:first-child) {
    width: 39%;
  }
}
</style>
