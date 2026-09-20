<template>
  <q-badge
    :class="['galaris-status-badge', `galaris-status-badge--${tone}`]"
  >
    <q-icon v-if="icon" :name="icon" size="12px" />
    <span>{{ label }}</span>
  </q-badge>
</template>

<script setup lang="ts">
import type { StatusBadgeTone } from '../statusBadge'

defineProps<{
  label: string
  tone: StatusBadgeTone
  icon?: string
}>()
</script>

<style scoped>
.galaris-status-badge {
  --galaris-status-color: #616161;

  display: inline-flex;
  align-items: center;
  gap: 4px;
  min-height: 12px;
  padding: 1px 5px !important;
  border: 1px solid var(--galaris-status-color);
  border-radius: 4px !important;
  background-color: var(--galaris-status-color) !important;
  color: #fff !important;
  font-size: 12px !important;
  font-weight: normal !important;
  line-height: 1 !important;
  white-space: nowrap;
}

.galaris-status-badge--active {
  --galaris-status-color: var(--q-primary);
}

.galaris-status-badge--success {
  --galaris-status-color: var(--q-positive);
}

.galaris-status-badge--warning {
  --galaris-status-color: #b45309;
}

.galaris-status-badge--error {
  --galaris-status-color: var(--q-negative);
}

.galaris-status-badge--neutral {
  --galaris-status-color: #616161;
}
</style>
