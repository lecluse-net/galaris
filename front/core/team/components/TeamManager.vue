<template>
  <div>
    <q-banner v-if="error" class="q-mb-md" role="alert">
      {{ t('team.error') }}<template #action><q-btn flat :label="t('team.retry')" @click="load" /></template>
    </q-banner>
    <q-table :rows="teams" :columns="columns" row-key="id" :loading="loading || reordering" :filter="search" :grid="$q.screen.lt.md"
      :rows-per-page-options="[10, 20, 50, 100, 500]" :pagination="{ rowsPerPage: 50 }">
      <template #top>
        <q-input v-model="search" dense outlined :label="t('common.search')" />
        <q-space />
        <q-btn v-if="canEdit" color="primary" icon="add" :label="t('team.create')" :disable="loading || reordering || error" @click="edit()" />
      </template>
      <template #body="scope">
        <q-tr :props="scope" :data-team-id="scope.row.id" :class="ordering.rowClass(scope.row.id)"
          @dragover="ordering.over($event, scope.row.id)" @drop="ordering.drop($event, scope.row.id)">
          <q-td v-if="canEdit" key="position" :props="scope" auto-width>
            <q-btn v-bind="dragHandle(scope.row)" />
          </q-td>
          <q-td key="name" :props="scope"><q-btn flat no-caps class="text-weight-medium" :label="scope.row.name"
            :disable="loading || reordering || error" @click="edit(scope.row)" /></q-td>
          <q-td key="description" :props="scope">{{ scope.row.description }}</q-td>
          <q-td key="humans" :props="scope"><TeamHumanSummary :team="scope.row" /></q-td>
          <q-td v-for="entry in contributions" :key="entry.definition.key" :props="scope">
            <component :is="entry.definition.component" :members="entry.members" compact readonly
              :model-value="memberIds(entry, scope.row.id)" />
          </q-td>
          <q-td key="actions" :props="scope">
            <q-btn v-if="canEdit || canMembers" flat round icon="edit" :aria-label="t('common.edit')"
              :disable="loading || reordering || error" @click="edit(scope.row)" />
            <q-btn v-if="canEdit" flat round icon="delete" :aria-label="t('common.delete')" :disable="reordering" @click="pendingDelete = scope.row" />
          </q-td>
        </q-tr>
      </template>
      <template #item="scope">
        <div class="col-12 q-pa-xs" :data-team-id="scope.row.id" :class="ordering.rowClass(scope.row.id)"
          @dragover="ordering.over($event, scope.row.id)" @drop="ordering.drop($event, scope.row.id)"><q-card flat bordered>
          <q-card-section>
            <div class="row items-center">
              <q-btn v-if="canEdit" v-bind="dragHandle(scope.row)" />
              <q-btn flat no-caps class="text-h6" :label="scope.row.name" :disable="loading || reordering || error" @click="edit(scope.row)" />
              <q-space />
              <q-btn v-if="canEdit || canMembers" flat round icon="edit" :aria-label="t('common.edit')"
                :disable="loading || reordering || error" @click="edit(scope.row)" />
              <q-btn v-if="canEdit" flat round icon="delete" :aria-label="t('common.delete')" :disable="reordering" @click="pendingDelete = scope.row" />
            </div>
            <div v-if="scope.row.description" class="q-mb-md">{{ scope.row.description }}</div>
            <div class="text-caption q-mb-xs">{{ t('team.humans') }}</div>
            <TeamHumanSummary :team="scope.row" />
            <div v-for="entry in contributions" :key="entry.definition.key" class="q-mt-md">
              <div class="text-caption q-mb-xs">{{ t(entry.definition.labelKey) }}</div>
              <component :is="entry.definition.component" :members="entry.members" compact readonly
                :model-value="memberIds(entry, scope.row.id)" />
            </div>
          </q-card-section>
        </q-card></div>
      </template>
    </q-table>
    <q-dialog v-model="editing" @hide="editorClosed">
      <TeamEditor v-if="editing" :team="selected" :contributions="contributions"
        @close="editing = false" @saved="editing = false" @changed="changed = true" />
    </q-dialog>
    <q-dialog :model-value="!!pendingDelete" @update:model-value="value => { if (!value) pendingDelete = null }">
      <q-card style="width: 500px; max-width: 95vw">
        <q-card-section class="galaris-dialog-title row items-center">
          <div class="text-h6">{{ t('team.deleteTitle') }}</div><q-space />
          <q-btn v-close-popup flat round dense icon="close" :aria-label="t('common.close')" />
        </q-card-section>
        <q-card-section>{{ t('team.deleteImpact', { name: pendingDelete?.name }) }}</q-card-section>
        <q-card-actions class="galaris-dialog-actions" align="right">
          <q-btn flat v-close-popup :label="t('common.cancel')" />
          <q-btn color="primary" :loading="deleting" :label="t('common.delete')" @click="remove" />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, shallowRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuasar, type QTableColumn } from 'quasar'
import { usePrivilegeStore } from '@/core/authorize'
import { teamService, type Team } from '../services/teamService'
import { teamContributions, type LoadedTeamContribution } from '../contributions'
import TeamEditor from './TeamEditor.vue'
import TeamHumanSummary from './TeamHumanSummary.vue'
import { useTeamOrdering } from '../composables/useTeamOrdering'

const { t } = useI18n()
const $q = useQuasar()
const privileges = usePrivilegeStore()
const canEdit = computed(() => privileges.hasPrivilege('TEAM_ACCESS') && privileges.hasPrivilege('TEAM_EDIT'))
const canMembers = computed(() => privileges.hasPrivilege('TEAM_ACCESS') && privileges.hasPrivilege('TEAM_MEMBERS_EDIT'))
const teams = ref<Team[]>([])
const contributions = shallowRef<LoadedTeamContribution[]>([])
const search = ref('')
const loading = ref(false)
const error = ref(false)
const editing = ref(false)
const selected = ref<Team>()
const changed = ref(false)
const pendingDelete = ref<Team | null>(null)
const deleting = ref(false)
const reordering = ref(false)
const canReorder = computed(() => canEdit.value && !loading.value && !reordering.value && !error.value)
const ordering = useTeamOrdering(teams, canReorder, move)
const columns = computed<QTableColumn[]>(() => [
  ...(canEdit.value ? [{ name: 'position', field: 'order', label: '', align: 'left' as const }] : []),
  { name: 'name', field: 'name', label: t('team.name'), align: 'left' },
  { name: 'description', field: 'description', label: t('team.description'), align: 'left' },
  { name: 'humans', field: 'human_count', label: t('team.humans'), align: 'left' },
  ...contributions.value.map(entry => ({ name: entry.definition.key, field: (team: Team) => memberIds(entry, team.id).length,
    label: t(entry.definition.labelKey), align: 'left' as const })),
  { name: 'actions', field: 'id', label: t('common.actions'), align: 'right' },
])
function memberIds(entry: LoadedTeamContribution, teamId: number): number[] {
  return entry.members.filter(member => member.team_ids.includes(teamId)).map(member => member.id)
}
function dragHandle(team: Team) {
  return {
    flat: true, round: true, dense: true, icon: 'drag_indicator', class: 'team-drag-handle',
    draggable: canReorder.value, disable: !canReorder.value,
    'aria-label': t('team.moveNamed', { name: team.name }), title: t('team.moveHint'),
    onDragstart: (event: DragEvent) => ordering.start(event, team.id),
    onDragend: ordering.clear,
    onPointerdown: (event: PointerEvent) => ordering.pointerStart(event, team.id),
    onPointermove: ordering.pointerMove, onPointerup: ordering.pointerEnd, onPointercancel: ordering.clear,
    onKeydown: (event: KeyboardEvent) => {
      if (event.key !== 'ArrowUp' && event.key !== 'ArrowDown') return
      event.preventDefault()
      ordering.keyboardMove(team.id, event.key === 'ArrowUp' ? -1 : 1)
    },
  }
}
async function move(id: number, target: number, after: boolean): Promise<void> {
  if (!canReorder.value || id === target) return
  reordering.value = true
  try {
    await teamService.move(id, target, after)
    await load()
  } catch { error.value = true } finally { reordering.value = false }
}
async function load(): Promise<void> {
  loading.value = true
  error.value = false
  try {
    const [rows, entries] = await Promise.all([
      teamService.list(),
      Promise.all(teamContributions.filter(item => privileges.hasPrivilege(item.privilege))
        .map(async definition => ({ definition, members: await definition.load() }))),
    ])
    teams.value = rows
    contributions.value = entries
  } catch { error.value = true } finally { loading.value = false }
}
function edit(team?: Team): void {
  selected.value = team
  changed.value = false
  editing.value = true
}
function editorClosed(): void {
  if (changed.value) void load()
  selected.value = undefined
}
async function remove(): Promise<void> {
  if (!pendingDelete.value || !canEdit.value || deleting.value) return
  deleting.value = true
  try {
    await teamService.remove(pendingDelete.value.id)
    pendingDelete.value = null
    await load()
  } catch { error.value = true } finally { deleting.value = false }
}
onMounted(load)
</script>

<style scoped>
.team-drag-handle { cursor: grab; touch-action: none; color: var(--solaire-gray-accent); }
.team-drag-handle:active { cursor: grabbing; }
.team-dragging { opacity: .45; }
.team-drop-before { box-shadow: inset 0 3px var(--solaire-blue-accent); }
.team-drop-after { box-shadow: inset 0 -3px var(--solaire-blue-accent); }
</style>
