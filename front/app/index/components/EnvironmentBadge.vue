<template>
  <q-badge v-if="environmentLabel" class="environment-badge" :style="{ backgroundColor: environmentBadgeColor }">
    {{ $t(compact ? `${environmentLabel}Short` : environmentLabel) }}
    <q-tooltip v-if="compact">{{ $t(environmentLabel) }}</q-tooltip>
  </q-badge>
</template>

<script setup lang="ts">
import { environmentBadgeColor, environmentLabel } from '../environmentPresentation'

defineProps<{ compact?: boolean }>()
</script>

<style scoped>
.environment-badge {
  color: #ffffff;
  font-size: 0.65rem;
  font-weight: 700;
  line-height: 1.2;
  padding: 3px 6px;
  max-width: 100%;
  white-space: normal;
  text-align: center;
}
</style>
