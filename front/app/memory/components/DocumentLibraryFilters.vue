<template>
  <q-btn flat round dense icon="filter_list" :aria-label="t('documents.library.filters')">
    <q-badge v-if="activeCount" floating>{{ activeCount }}</q-badge>
    <q-tooltip>{{ t('documents.library.filters') }}</q-tooltip>
    <q-menu @before-show="draft = { ...model }">
      <q-form class="library-filters q-pa-md q-gutter-sm" @submit="apply">
        <div class="text-subtitle2">{{ t('documents.library.filters') }}</div>
        <q-toggle v-model="onlyUnclassified" dense :label="t('documents.library.unclassified')" />
        <q-select v-model="draft.document_type" dense outlined clearable emit-value map-options :label="t('documents.documentType')" :options="documentTypes" />
        <q-select v-model="draft.keyword" dense outlined clearable :label="t('documents.keywordFilter')" :options="keywords" />
        <q-select v-model="draft.owner_kind" dense outlined clearable emit-value map-options :label="t('documents.library.ownerKind')" :options="ownerKinds" @update:model-value="draft.owner = null" />
        <q-select v-model="draft.owner" dense outlined clearable emit-value map-options use-input input-debounce="0" :label="t('documents.library.owner')" :options="ownerOptions" @filter="filterOwners" :disable="!draft.owner_kind" />
        <div v-for="pair in datePairs" :key="pair.label">
          <div class="text-caption q-mb-xs">{{ t(`documents.library.${pair.label}`) }}</div>
          <div class="row no-wrap q-gutter-sm">
            <q-input v-for="field in pair.fields" :key="field.key" v-model="draft[field.key]" class="col" dense outlined type="date" stack-label
              :label="t(`documents.library.${field.boundary}`)" :aria-label="t(`documents.library.${field.label}`)" />
          </div>
        </div>
        <q-select v-model="draft.sort_by" dense outlined emit-value map-options :label="t('documents.library.sort')" :options="sortOptions" />
        <q-checkbox v-model="draft.sort_desc" dense :label="t('documents.library.descending')" />
        <div v-if="invalidDates" role="alert">{{ t('documents.library.invalidDates') }}</div>
        <div class="row justify-end q-gutter-sm">
          <q-btn flat :label="t('documents.library.reset')" @click="draft = defaults(); onlyUnclassified = true" />
          <q-btn type="submit" color="primary" :disable="invalidDates" :label="t('documents.library.apply')" v-close-popup="!invalidDates" />
        </div>
      </q-form>
    </q-menu>
  </q-btn>
</template>
<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import type { DocumentOwnerOption } from '../types'
import { defaultLibraryFilters as defaults, type LibraryFilterState } from '../libraryFilterState'
const model = defineModel<LibraryFilterState>({ required: true })
const onlyUnclassified = defineModel<boolean>('onlyUnclassified', { required: true })
const props = defineProps<{ owners: DocumentOwnerOption[]; keywords: string[] }>()
const { t } = useI18n()
const draft = ref({ ...model.value })
const ownerSearch = ref('')
const dateFields = [
  { key: 'created_from', label: 'createdFrom', boundary: 'from' }, { key: 'created_until', label: 'createdUntil', boundary: 'until' },
  { key: 'updated_from', label: 'updatedFrom', boundary: 'from' }, { key: 'updated_until', label: 'updatedUntil', boundary: 'until' },
] as const
const datePairs = [{ label: 'created', fields: dateFields.slice(0, 2) }, { label: 'updated', fields: dateFields.slice(2) }]
const invalidDates = computed(() => Boolean((draft.value.created_from && draft.value.created_until && draft.value.created_from > draft.value.created_until)
  || (draft.value.updated_from && draft.value.updated_until && draft.value.updated_from > draft.value.updated_until)))
const ownerKinds = computed(() => ['agent', 'user'].map(value => ({ value, label: t(`documents.library.${value}`) })))
const documentTypes = computed(() => ['html', 'dataset'].map(value => ({ value, label: t(`documents.types.${value}`) })))
const sortOptions = computed(() => [
  { value: 'position', label: t('documents.library.manualOrder') },
  { value: 'document_type', label: t('documents.documentType') },
  { value: 'title', label: t('documents.library.title') }, { value: 'created_at', label: t('documents.library.created') }, { value: 'updated_at', label: t('documents.library.updated') },
])
const ownerOptions = computed(() => props.owners.filter(owner => owner.kind === draft.value.owner_kind && owner.label.toLocaleLowerCase().includes(ownerSearch.value)).map(owner => ({ value: owner.id, label: owner.label })))
const activeCount = computed(() => Number(onlyUnclassified.value) + Number(Boolean(model.value.document_type)) + Number(Boolean(model.value.owner_kind)) + Number(Boolean(model.value.keyword))
  + dateFields.filter(field => model.value[field.key]).length + Number(model.value.sort_by !== 'position' || model.value.sort_desc))
function filterOwners(value: string, update: (callback: () => void) => void): void { update(() => { ownerSearch.value = value.toLocaleLowerCase() }) }
function apply(): void { if (!invalidDates.value) model.value = { ...draft.value } }
</script>
<style scoped>
.library-filters { width: min(420px, calc(100vw - 24px)); max-height: 80vh; overflow: auto; }
</style>
