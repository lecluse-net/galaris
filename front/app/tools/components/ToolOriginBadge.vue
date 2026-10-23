<template>
  <q-badge v-if="tool" class="tool-origin-badge" :class="`tool-origin-badge--${toolOrigin(tool)}`">
    {{ $t(`tools.origins.${toolOrigin(tool)}`) }}
  </q-badge>
</template>

<script setup lang="ts">
import { toolOrigin } from '../presentation'
import type { Tool } from '../services/toolService'

defineProps<{ tool?: Pick<Tool, 'code' | 'can_edit'> }>()
</script>

<style scoped>
.tool-origin-badge {
  color: inherit;
  font-size: 0.7rem;
  font-weight: normal;
  vertical-align: middle;
}
.tool-origin-badge--galaris { background: var(--solaire-blue-light); }
.tool-origin-badge--custom { background: var(--solaire-violet-light); }
.body--dark .tool-origin-badge--galaris { background: var(--solaire-blue-dark); }
.body--dark .tool-origin-badge--custom { background: var(--solaire-violet-dark); }
</style>
