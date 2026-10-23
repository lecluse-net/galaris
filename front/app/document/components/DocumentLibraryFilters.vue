<template>
  <q-btn flat round dense icon="filter_list" :aria-label="t('documents.library.filters')">
    <q-badge v-if="activeCount" floating>{{ activeCount }}</q-badge>
    <q-tooltip>{{ t('documents.library.filters') }}</q-tooltip>
    <q-menu @before-show="draft = { ...model }">
      <q-form class="library-filters q-pa-md q-gutter-sm" @submit="apply">
        <div class="text-subtitle2">{{ t('documents.library.filters') }}</div>
        <q-toggle v-model="onlyUnclassified" dense :label="t('documents.library.unclassified')" />
        <q-select v-model="draft.keyword" dense outlined clearable :label="t('documents.keywordFilter')" :options="keywords" />
        <OwnerSelect v-model="ownerSelection" :options="ownerOptions" :current-user-id="currentUserId" clearable />
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
import { OwnerSelect } from '@/app/share'
import { defaultLibraryFilters as defaults, type LibraryFilterState } from '@/app/document/libraryFilterState'
const model = defineModel<LibraryFilterState>({ required: true })
const onlyUnclassified = defineModel<boolean>('onlyUnclassified', { required: true })
const { owners, currentUserId } = defineProps<{ owners: DocumentOwnerOption[]; keywords: string[]; currentUserId?: number }>()
const { t } = useI18n()
const ownerOptions = computed(() => currentUserId && !owners.some(owner => owner.kind === 'user' && owner.id === currentUserId)
  ? [{ kind: 'user' as const, id: currentUserId, label: t('resourceOwner.me'), is_current_user: true }, ...owners]
  : owners)
const draft = ref({ ...model.value })
const ownerSelection = computed({
  get: () => draft.value.owner_kind && draft.value.owner !== null ? `${draft.value.owner_kind}:${draft.value.owner}` : '',
  set: (key: string) => {
    const [kind, id] = key.split(':')
    draft.value.owner_kind = kind === 'user' || kind === 'agent' ? kind : null
    draft.value.owner = draft.value.owner_kind ? Number(id) : null
  },
})
const dateFields = [
  { key: 'created_from', label: 'createdFrom', boundary: 'from' }, { key: 'created_until', label: 'createdUntil', boundary: 'until' },
  { key: 'updated_from', label: 'updatedFrom', boundary: 'from' }, { key: 'updated_until', label: 'updatedUntil', boundary: 'until' },
] as const
const datePairs = [{ label: 'created', fields: dateFields.slice(0, 2) }, { label: 'updated', fields: dateFields.slice(2) }]
const invalidDates = computed(() => Boolean((draft.value.created_from && draft.value.created_until && draft.value.created_from > draft.value.created_until)
  || (draft.value.updated_from && draft.value.updated_until && draft.value.updated_from > draft.value.updated_until)))
const sortOptions = computed(() => [
  { value: 'position', label: t('documents.library.manualOrder') },
  { value: 'title', label: t('documents.library.title') }, { value: 'created_at', label: t('documents.library.created') }, { value: 'updated_at', label: t('documents.library.updated') },
])
const activeCount = computed(() => Number(onlyUnclassified.value) + Number(Boolean(model.value.owner_kind)) + Number(Boolean(model.value.keyword))
  + dateFields.filter(field => model.value[field.key]).length + Number(model.value.sort_by !== 'position' || model.value.sort_desc))
function apply(): void { if (!invalidDates.value) model.value = { ...draft.value } }
</script>
<style scoped>
.library-filters { width: min(420px, calc(100vw - 24px)); max-height: 80vh; overflow: auto; }
</style>
