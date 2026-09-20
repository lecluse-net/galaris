<template>
  <div class="recipient-picker">
    <q-input v-model="query" outlined dense autofocus clearable :label="t('resourceSharing.search')">
      <template #prepend><q-icon name="search" size="18px" /></template>
    </q-input>
    <div class="recipient-filters" role="group" :aria-label="t('resourceSharing.filter')">
      <q-btn v-for="filter in filters" :key="filter.value" dense no-caps
        :outline="kind !== filter.value" :unelevated="kind === filter.value" :color="kind === filter.value ? 'primary' : undefined"
        :icon="kind === filter.value ? 'check' : undefined" :label="filter.label" :aria-pressed="kind === filter.value"
        @click="kind = filter.value" />
    </div>
    <div ref="results" class="recipient-results">
      <q-list dense :aria-label="t('resourceSharing.results')">
        <q-item v-for="option in pageOptions" :key="`${option.kind}:${option.id}`" class="recipient-row">
          <q-item-section avatar>
            <slot v-if="option.kind !== 'team'" name="avatar" :recipient="option" size="28px">
              <PersonAvatar :name="option.label" :avatar-url="option.avatar_url" size="28px" />
            </slot>
            <q-icon v-else name="groups" size="18px" />
          </q-item-section>
          <q-item-section class="recipient-name">
            <q-item-label>{{ option.label }}</q-item-label>
            <q-item-label caption>{{ t('resourceSharing.kind.' + option.kind) }}</q-item-label>
          </q-item-section>
          <q-item-section side>
            <div class="recipient-actions">
              <q-btn v-for="write in [false, true]" :key="String(write)" outline round dense color="primary" size="sm"
                :icon="write ? 'edit' : 'visibility'" :disable="disabled || !(write ? option.can_grant_write : option.can_grant_read)"
                :aria-label="t('resourceSharing.grantRight', { name: option.label, right: t(write ? 'resourceSharing.write' : 'resourceSharing.read') })"
                @click="emit('grant', option, write)">
                <q-tooltip>{{ t(write ? 'resourceSharing.write' : 'resourceSharing.read') }}</q-tooltip>
              </q-btn>
            </div>
          </q-item-section>
        </q-item>
        <q-item v-if="!filteredOptions.length"><q-item-section class="text-caption">{{ t('resourceSharing.noResults') }}</q-item-section></q-item>
      </q-list>
    </div>
    <div v-if="filteredOptions.length" class="recipient-pagination">
      <span class="text-caption" aria-live="polite">{{ t('resourceSharing.resultRange', { from: firstResult, to: lastResult, total: filteredOptions.length }) }}</span>
      <div v-if="filteredOptions.length > 10" class="recipient-page-controls">
        <q-select v-model="pageSize" :options="[10, 20, 50, 100, 500]" dense borderless hide-bottom-space
          class="recipient-page-size" :aria-label="t('resourceSharing.perPage')" />
        <q-btn flat round dense size="sm" icon="chevron_left" :disable="page === 1"
          :aria-label="t('resourceSharing.previousPage')" @click="page--" />
        <q-btn flat round dense size="sm" icon="chevron_right" :disable="page === pageCount"
          :aria-label="t('resourceSharing.nextPage')" @click="page++" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { SharingChoice, SharingRecipient } from '../sharing'
import PersonAvatar from './PersonAvatar.vue'

const props = defineProps<{ options: SharingChoice[]; disabled: boolean }>()
const emit = defineEmits<{ grant: [recipient: SharingRecipient, write: boolean] }>()
const { t } = useI18n()
const query = ref<string | null>('')
const kind = ref<'all' | SharingRecipient['kind']>('all')
const page = ref(1)
const pageSize = ref(10)
const results = useTemplateRef<HTMLElement>('results')
const normalize = (value: string): string => value.normalize('NFD').replace(/\p{M}/gu, '').toLocaleLowerCase()
const normalizedQuery = computed(() => normalize(query.value ?? ''))
const filters = computed(() => [
  { label: t('resourceSharing.filterAll'), value: 'all' as const },
  { label: t('resourceSharing.groups'), value: 'team' as const },
  { label: t('resourceSharing.people'), value: 'user' as const },
  { label: t('resourceSharing.agents'), value: 'agent' as const },
])
const filteredOptions = computed(() => props.options
  .filter(value => kind.value === 'all' || value.kind === kind.value)
  .filter(value => normalize(value.label).includes(normalizedQuery.value)))
const pageCount = computed(() => Math.max(1, Math.ceil(filteredOptions.value.length / pageSize.value)))
const firstResult = computed(() => (page.value - 1) * pageSize.value + 1)
const lastResult = computed(() => Math.min(page.value * pageSize.value, filteredOptions.value.length))
const pageOptions = computed(() => filteredOptions.value.slice(firstResult.value - 1, lastResult.value))
watch([query, kind, pageSize], () => { page.value = 1 })
watch(pageCount, count => { page.value = Math.min(page.value, count) })
watch([page, query, kind, pageSize], () => { results.value?.scrollTo({ top: 0 }) }, { flush: 'post' })
</script>

<style scoped>
.recipient-picker { padding: 8px; }
.recipient-filters { display: flex; gap: 4px; padding: 4px 0; }
.recipient-filters .q-btn { padding: 2px 8px; font-size: 12px; }
.recipient-actions { display: flex; gap: 6px; }
.recipient-results { max-height: 250px; overflow-y: auto; }
.recipient-row { padding: 2px 0; }
.recipient-row :deep(.q-item__section--avatar) { min-width: 34px; padding-right: 6px; color: var(--solaire-blue-accent); }
.recipient-row :deep(.q-item__section--side) { padding-left: 6px; }
.recipient-row :deep(.q-btn) { padding: 2px 6px; font-size: 12px; }
.recipient-name { min-width: 0; overflow-wrap: anywhere; }
.recipient-pagination, .recipient-page-controls { display: flex; align-items: center; gap: 4px; }
.recipient-pagination { justify-content: space-between; border-top: 1px solid var(--solaire-gray-light); margin-top: 4px; }
.recipient-page-size { width: 56px; }
.recipient-page-size :deep(.q-field__control), .recipient-page-size :deep(.q-field__marginal) { height: 28px; min-height: 28px; }
:global(.body--dark) .recipient-pagination { border-color: var(--solaire-gray-dark); }
</style>
