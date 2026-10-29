<template>
  <div class="permission-browser">
    <aside :aria-label="t('connection.tool')" class="permission-tool-list">
      <q-list bordered separator class="relative-position">
          <q-item v-for="entry in entries" :key="entry.id" clickable :active="selected?.id === entry.id" active-class="permission-tool-selected"
            :aria-label="entry.title" :aria-current="selected?.id === entry.id ? 'true' : undefined"
            @click="selectedId = entry.id">
            <q-item-section><q-item-label class="permission-text">{{ entry.title }}</q-item-label>
              <q-item-label caption>{{ entry.scope }}</q-item-label></q-item-section>
            <q-item-section side><q-icon :name="permissionStates[entry.state].icon"
              :style="{ color: solaireCss[permissionStates[entry.state].color].accent }">
              <q-tooltip>{{ t(entry.state === 'allowed' ? 'connection.active' : 'connection.inactive') }}</q-tooltip>
            </q-icon></q-item-section>
          </q-item>
          <q-item v-if="!entries.length"><q-item-section>{{ t(loading ? 'permissions.loading' : 'permissions.empty') }}</q-item-section></q-item>
          <q-inner-loading :showing="loading" color="primary" :aria-label="t('permissions.loading')" />
      </q-list>
    </aside>
    <q-card v-if="selected" tag="section" role="group" :aria-label="selected.title" flat bordered class="permission-tool-detail">
      <q-card-section>
        <div class="row items-center q-gutter-sm"><h3 class="text-h6 q-my-none">{{ selected.title }}</h3>
          <PermissionStateBadge :state="selected.state" :label="t(selected.state === 'allowed' ? 'connection.active' : 'connection.inactive')" />
        </div>
        <div class="text-caption">{{ selected.scope }}</div>
        <div class="permission-tool-controls q-mt-md">
          <PermissionToggle v-for="control in orderedControls" :key="`${selected.id}:${control.id}`" :control="control"
            :disabled="busy || loading" show-label @change="value => emit('change', selected!, control, value)" />
        </div>
        <div class="text-caption permission-text q-mt-md">{{ selected.origin }}</div>
        <div v-if="selected.note" class="text-caption permission-text">{{ selected.note }}</div>
        <div v-if="selected.description" class="text-caption permission-text q-mt-sm">{{ selected.description }}</div>
      </q-card-section>
      <q-separator />
      <q-card-section class="permission-functions">
        <PermissionEntryTable :key="`${selected.id}:${filterKey}`" :entries="selected.children ?? []" nested :busy="busy" :loading="loading"
          @change="(entry, control, value) => emit('change', entry, control, value)" />
      </q-card-section>
    </q-card>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { solaireCss } from '@/core/util'
import { permissionStates } from '../permissionPresentation'
import type { PermissionControl, PermissionEntry } from '../services/permissionDashboard'
import PermissionEntryTable from './PermissionEntryTable.vue'
import PermissionToggle from './PermissionToggle.vue'
import PermissionStateBadge from './PermissionStateBadge.vue'

const { entries, loading = false, busy = false, filterKey = '' } = defineProps<{
  entries: PermissionEntry[]; loading?: boolean; busy?: boolean; filterKey?: string
}>()
const emit = defineEmits<{
  change: [entry: PermissionEntry, control: PermissionControl, value: string]
}>()
const { t } = useI18n()
const selectedId = ref<string | null>(null)
const selected = computed(() => entries.find(entry => entry.id === selectedId.value) ?? entries[0])
const orderedControls = computed(() => [...(selected.value?.controls ?? [])].sort((a, b) => Number(b.id === 'scope') - Number(a.id === 'scope')))
watch(() => selected.value?.id, id => { if (id) selectedId.value = id })
</script>

<style scoped>
.permission-browser { display: grid; grid-template-columns: minmax(0, 1fr); gap: 16px; align-items: start; }
.permission-tool-list, .permission-tool-detail { min-width: 0; }
.permission-text { overflow-wrap: anywhere; white-space: pre-wrap; }
.permission-tool-selected { color: inherit; background: var(--solaire-blue-light); box-shadow: inset 3px 0 var(--solaire-blue-accent); }
.permission-tool-controls { display: flex; flex-wrap: wrap; align-items: start; gap: 16px 24px; }
body.body--dark .permission-tool-selected { background: var(--solaire-blue-dark); }
@media (min-width: 1024px) {
  .permission-browser { grid-template-columns: minmax(204px, 23.8%) minmax(0, 1fr); }
}
@media (max-width: 1023px) {
  .permission-functions { padding: 8px; }
}
</style>
