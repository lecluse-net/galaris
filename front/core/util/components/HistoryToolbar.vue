<template>
  <q-card-section class="history-toolbar row items-center justify-between no-wrap">
    <div class="history-toolbar__title row items-center no-wrap">
      <q-icon name="history" size="sm" class="q-mr-sm" />
      <span class="text-subtitle1">{{ title }}</span>
    </div>
    <div class="history-toolbar__filters row items-center">
      <q-input :model-value="search" outlined dense clearable debounce="300" :label="searchLabel"
        class="history-toolbar__search" @update:model-value="updateSearch">
        <template #prepend><q-icon name="search" /></template>
      </q-input>
      <slot />
    </div>
  </q-card-section>
</template>

<script setup lang="ts">
defineProps<{ title: string; searchLabel: string }>()
const search = defineModel<string>('search', { required: true })
const emit = defineEmits<{ change: [] }>()

function updateSearch(value: string | number | null): void {
  search.value = value == null ? '' : String(value)
  emit('change')
}
</script>

<style scoped>
.history-toolbar { gap: 12px; }
.history-toolbar__title { flex: 0 0 auto; }
.history-toolbar__filters {
  flex: 1 1 auto;
  flex-wrap: nowrap;
  justify-content: flex-end;
  gap: 8px;
  min-width: 0;
}
.history-toolbar__search {
  flex: 0 1 220px;
  width: 220px;
  min-width: 140px;
  max-width: 220px;
}
:slotted(.history-toolbar-filter) {
  flex: 0 1 180px;
  width: 180px;
  min-width: 130px;
  max-width: 180px;
}
:slotted(.history-toolbar-filter--wide) {
  flex-basis: 220px;
  width: 220px;
  min-width: 150px;
  max-width: 220px;
}
@media (max-width: 1023px) {
  .history-toolbar { flex-wrap: wrap; }
  .history-toolbar__title,
  .history-toolbar__filters { width: 100%; }
  .history-toolbar__filters {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .history-toolbar__search,
  :slotted(.history-toolbar-filter) { width: 100%; min-width: 0; max-width: none; }
  .history-toolbar__search,
  :slotted(.history-toolbar-dates) { grid-column: 1 / -1; }
}
@media (max-width: 599px) {
  .history-toolbar__filters { grid-template-columns: minmax(0, 1fr); }
  .history-toolbar__search,
  :slotted(.history-toolbar-dates) { grid-column: auto; }
}
</style>
