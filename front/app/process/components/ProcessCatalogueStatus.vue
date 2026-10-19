<template>
  <div class="catalogue-status">
    <div v-if="item.latest_run" class="row items-center q-gutter-xs">
      <span>{{ t('processes.catalogue.latestRun') }}</span>
      <ProcessRunStatusBadge :status="item.latest_run.status" />
      <span class="text-caption">{{ new Date(item.latest_run.created_at).toLocaleString(locale) }}</span>
    </div>
    <span v-else class="text-caption">{{ t('processes.catalogue.neverRun') }}</span>
    <div v-if="item.active_runs || item.human_waiting_runs" class="row q-gutter-xs">
      <q-badge v-if="item.active_runs" class="active-count">{{ t('processes.catalogue.activeRuns', { count: item.active_runs }) }}</q-badge>
      <q-badge v-if="item.human_waiting_runs" class="human-count">{{ t('processes.catalogue.humanWaiting', { count: item.human_waiting_runs }) }}</q-badge>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import type { CatalogueItem } from '../services/catalogueService'
import ProcessRunStatusBadge from './ProcessRunStatusBadge.vue'
defineProps<{ item: CatalogueItem }>()
const { t, locale } = useI18n()
</script>

<style scoped>
.catalogue-status { display: grid; gap: 6px; white-space: normal; }
.active-count { background: var(--solaire-blue-light); color: inherit; }
.human-count { background: var(--solaire-orange-light); color: inherit; }
body.body--dark .active-count { background: var(--solaire-blue-dark); }
body.body--dark .human-count { background: var(--solaire-orange-dark); }
</style>
