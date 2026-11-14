<template>
  <div>
    <div class="row items-center q-gutter-sm q-mb-md">
      <q-input v-model="search" outlined dense clearable :label="t('services.searchCatalog')" class="col">
        <template #prepend><q-icon name="search" /></template>
      </q-input>
      <q-btn v-if="canEdit" outline color="primary" icon="sync" :label="t('services.refreshCatalog')" :loading="loading" @click="load(true)" />
    </div>
    <p>{{ t('services.catalogHint') }}</p>
    <q-linear-progress v-if="loading" indeterminate color="primary" class="q-mb-md" />
    <q-banner v-if="error" role="alert" class="q-mb-md">{{ error }}
      <template #action><q-btn outline color="primary" :label="t('common.retry')" @click="load(false)" /></template>
    </q-banner>
    <p v-if="catalog" class="text-caption">{{ t(`services.catalogSources.${catalog.source}`) }}
      <span v-if="catalog.source === 'github'"> · {{ catalog.revision.slice(0, 12) }}</span>
    </p>
    <q-table :rows="entries" :columns="columns" row-key="code" :loading="loading" :grid="$q.screen.lt.md"
      :rows-per-page-options="[10, 20, 50, 100, 500]" :pagination="{ rowsPerPage: 50 }" :no-data-label="t('services.emptyCatalog')">
      <template #body-cell-label="props"><q-td :props="props">
        <ServiceIcon :icon="props.row.definition.icon" class="q-mr-sm" />{{ props.row.definition.label }}
      </q-td></template>
      <template #body-cell-actions="props"><q-td :props="props">
        <ServicePresetAction :entry="props.row" :installed="installed" :can-edit="canEdit" @select="emit('select', $event)" />
      </q-td></template>
      <template #item="props"><div class="col-12 q-mb-sm"><q-card flat bordered><q-card-section>
        <div class="row items-center q-gutter-sm"><ServiceIcon :icon="props.row.definition.icon" /><strong>{{ props.row.definition.label }}</strong></div>
        <p class="q-mt-sm">{{ summary(props.row) }}</p>
        <ServicePresetAction :entry="props.row" :installed="installed" :can-edit="canEdit" @select="emit('select', $event)" />
      </q-card-section></q-card></div></template>
    </q-table>
  </div>
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import ServiceIcon from './ServiceIcon.vue'
import ServicePresetAction from './ServicePresetAction.vue'
import serviceApi, { type Service, type ServiceCatalog, type ServiceCreate, type ServicePreset } from '../services/serviceApi'
const { installed } = defineProps<{ installed: Service[] }>()
const emit = defineEmits<{ select: [definition: ServiceCreate] }>()
const { t, locale } = useI18n(), privilegeStore = usePrivilegeStore()
const canEdit = computed(() => privilegeStore.hasPrivilege(privileges.SERVICE_EDIT))
const catalog = ref<ServiceCatalog | null>(null), loading = ref(false), error = ref(''), search = ref<string | null>('')
let generation = 0
onBeforeUnmount(() => generation++)
async function load(refresh: boolean) {
  if (loading.value) return
  const current = ++generation
  loading.value = true; error.value = ''
  try {
    const { data } = await (refresh ? serviceApi.refreshCatalog() : serviceApi.getCatalog())
    if (current !== generation) return
    catalog.value = data
    if (data.refresh_failed) error.value = t('services.catalogRefreshError')
  } catch { if (current === generation) error.value = t('services.catalogLoadError') }
  finally { if (current === generation) loading.value = false }
}
onMounted(() => load(false))
function summary(entry: ServicePreset) {
  const summaries = entry.definition.catalog?.summary
  return summaries?.[locale.value] ?? summaries?.en ?? entry.definition.description ?? ''
}
const entries = computed(() => (catalog.value?.entries ?? []).map(entry => ({ ...entry, code: entry.definition.code }))
  .filter(entry => `${entry.definition.label} ${entry.definition.code} ${summary(entry)}`.toLocaleLowerCase().includes((search.value ?? '').toLocaleLowerCase())))
const columns = computed(() => [
  { name: 'label', label: t('services.labelColumn'), field: (entry: ServicePreset) => entry.definition.label, align: 'left' as const, sortable: true },
  { name: 'summary', label: t('services.catalogDescription'), field: summary, align: 'left' as const, style: 'white-space: normal' },
  { name: 'actions', label: '', field: '', align: 'right' as const },
])
</script>
