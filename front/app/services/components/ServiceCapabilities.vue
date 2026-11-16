<template>
  <div class="row items-center q-gutter-xs" :aria-label="t('services.capabilities')">
    <q-badge v-for="value in toolCapabilitySelections(tool)" :key="value" outline color="solaire-orange" class="capability-badge">
      {{ capabilityLabels(value, definitions, t).capability }}
    </q-badge>
  </div>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import type { CapabilityDefinition, Service } from '../services/serviceApi'
import { capabilityLabels, toolCapabilitySelections } from '../capabilities'

const { tool, definitions } = defineProps<{ tool: Service; definitions: CapabilityDefinition[] }>()
const { t } = useI18n()
</script>

<style scoped>
.capability-badge { white-space: normal; overflow-wrap: anywhere; }
</style>
