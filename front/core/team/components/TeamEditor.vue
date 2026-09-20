<template>
  <q-card class="team-editor">
    <q-card-section class="galaris-dialog-title row items-center">
      <div class="text-h6">{{ t(team ? (canEdit || canMembers ? 'team.edit' : 'team.details') : 'team.create') }}</div>
      <q-space />
      <q-btn flat round dense icon="close" :aria-label="t('common.close')" @click="emit('close')" />
    </q-card-section>
    <q-form @submit="save">
      <div class="team-editor-body">
        <q-card-section>
          <div class="row q-col-gutter-md">
            <q-input v-model="form.name" class="col-12" outlined dense :readonly="!canEdit" :disable="saving"
              :label="t('team.name')" :rules="[v => !!String(v).trim() || t('team.required')]" maxlength="255" />
            <q-input v-model="form.description" class="col-12" outlined dense autogrow
              :readonly="!canEdit" :disable="saving" :label="t('team.description')" maxlength="4000" />
          </div>
        </q-card-section>
        <q-separator />
        <q-card-section>
          <q-banner v-if="loadError" class="q-mb-md" role="alert">
            {{ t('team.error') }}
            <template #action><q-btn flat :label="t('team.retry')" @click="loadHumans" /></template>
          </q-banner>
          <q-linear-progress v-if="loading" indeterminate class="q-mb-md" />
          <div class="row q-col-gutter-xl">
            <section class="col-12 col-md-6" :aria-label="t('team.humans')">
              <div class="text-subtitle1 q-mb-md">{{ t('team.humans') }} <q-badge color="primary" :label="humans.length" /></div>
              <q-banner v-if="searchError" class="q-mb-sm" role="alert">{{ t('team.error') }}</q-banner>
              <div v-if="canMembers" class="row items-start no-wrap q-gutter-sm q-mb-md">
                <UserSelect v-model="selectedHuman" class="col" outlined dense use-input clearable
                  :options="humanOptions" :label="t('team.addHuman')" :disable="saving || loading || loadError"
                  input-debounce="200" @filter="filterHumans" @filter-abort="invalidateSearch" @popup-hide="invalidateSearch" />
                <q-btn color="primary" icon="add" :label="t('team.add')"
                  :disable="selectedHuman === null || saving || loading || loadError" @click="addHuman" />
              </div>
              <q-list bordered separator class="rounded-borders">
                <q-item v-for="member in humans" :key="member.id">
                  <q-item-section avatar><UserAvatar :name="member.label" :avatar-url="member.avatar_url" /></q-item-section>
                  <q-item-section>{{ member.label }}<q-item-label v-if="!member.active" caption>{{ t('team.inactive') }}</q-item-label></q-item-section>
                  <q-item-section v-if="canMembers" side>
                    <q-btn flat round icon="close" :disable="saving" :aria-label="t('team.removeNamed', { name: member.label })"
                      @click="humans = humans.filter(human => human.id !== member.id)" />
                  </q-item-section>
                </q-item>
                <q-item v-if="!humans.length && !loading"><q-item-section class="text-grey-7">{{ t('team.empty') }}</q-item-section></q-item>
              </q-list>
            </section>
            <div v-for="entry in contributions" :key="entry.definition.key" class="col-12 col-md-6">
              <component :is="entry.definition.component" v-model="drafts[entry.definition.key]" :members="entry.members"
                :readonly="!canMembers" :disabled="saving || loading || loadError" />
            </div>
          </div>
        </q-card-section>
      </div>
      <q-separator />
      <q-card-section v-if="saveError" class="q-pb-none" role="alert">{{ t('team.saveError') }}</q-card-section>
      <q-card-actions align="right" class="q-pa-md galaris-dialog-actions">
        <q-btn flat :label="t(canEdit || canMembers ? 'common.cancel' : 'common.close')" @click="emit('close')" />
        <q-btn v-if="canEdit || canMembers" color="primary" type="submit" :label="t('common.save')"
          :loading="saving" :disable="loading || loadError" />
      </q-card-actions>
    </q-form>
  </q-card>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { isCancelledRequest } from '@/core/api'
import { useI18n } from 'vue-i18n'
import { usePrivilegeStore } from '@/core/authorize'
import { UserAvatar, UserSelect } from '@/core/user'
import { teamService, type Human, type Team } from '../services/teamService'
import type { LoadedTeamContribution } from '../contributions'

const { team, contributions } = defineProps<{ team?: Team; contributions: LoadedTeamContribution[] }>()
const emit = defineEmits<{ close: []; saved: []; changed: [] }>()
const { t } = useI18n()
const privileges = usePrivilegeStore()
const canEdit = computed(() => privileges.hasPrivilege('TEAM_ACCESS') && privileges.hasPrivilege('TEAM_EDIT'))
const canMembers = computed(() => privileges.hasPrivilege('TEAM_ACCESS') && privileges.hasPrivilege('TEAM_MEMBERS_EDIT'))
const form = ref({ name: team?.name ?? '', description: team?.description ?? '' })
let savedId = team?.id
const humans = ref<Human[]>([])
const originalHumans = new Set<number>()
const selectedHuman = ref<number | null>(null)
const humanResults = ref<Human[]>([])
const loading = ref(true)
const loadError = ref(false)
const saving = ref(false)
const saveError = ref(false)
const searchError = ref(false)
const drafts = ref<Record<string, number[]>>({})
const originals = new Map<string, Set<number>>()
for (const entry of contributions) {
  const ids = entry.members.filter(member => team && member.team_ids.includes(team.id)).map(member => member.id)
  drafts.value[entry.definition.key] = ids
  originals.set(entry.definition.key, new Set(ids))
}
const humanOptions = computed(() => humanResults.value.filter(human => !humans.value.some(member => member.id === human.id))
  .map(human => ({ value: human.id, label: human.label, avatarUrl: human.avatar_url, caption: human.active ? '' : t('team.inactive') })))

async function loadHumans(): Promise<void> {
  loading.value = true
  loadError.value = false
  try {
    humans.value = team ? await teamService.members(team.id) : []
    originalHumans.clear()
    for (const member of humans.value) originalHumans.add(member.id)
  } catch { loadError.value = true } finally { loading.value = false }
}
let searchVersion = 0
function invalidateSearch(): void { searchVersion += 1 }
onBeforeUnmount(invalidateSearch)
async function filterHumans(value: string, update: (callback: () => void) => void, abort: () => void): Promise<void> {
  const version = ++searchVersion
  searchError.value = false
  try {
    const rows = await teamService.humans(value)
    if (version !== searchVersion) return
    update(() => { humanResults.value = rows })
  } catch (error) {
    if (version !== searchVersion) return
    searchError.value = !isCancelledRequest(error)
    abort()
  }
}
function addHuman(): void {
  if (!canMembers.value || saving.value) return
  const human = humanResults.value.find(member => member.id === selectedHuman.value)
  if (human && !humans.value.some(member => member.id === human.id)) humans.value = [...humans.value, human]
  selectedHuman.value = null
}
async function saveMemberships(id: number, desired: number[], original: Set<number>, write: (teamId: number, memberId: number, present: boolean) => Promise<void>): Promise<void> {
  for (const memberId of new Set([...original, ...desired])) {
    const present = desired.includes(memberId)
    if (present === original.has(memberId)) continue
    await write(id, memberId, present)
    if (present) original.add(memberId)
    else original.delete(memberId)
    emit('changed')
  }
}
async function save(): Promise<void> {
  if (saving.value || loading.value || loadError.value || (!canEdit.value && !canMembers.value)) return
  saving.value = true
  saveError.value = false
  try {
    if (canEdit.value) {
      savedId = (await teamService.save(form.value, savedId)).id
      emit('changed')
    }
    if (savedId === undefined) return
    if (canMembers.value) {
      await saveMemberships(savedId, humans.value.map(human => human.id), originalHumans, teamService.membership)
      for (const entry of contributions) {
        const key = entry.definition.key
        await saveMemberships(savedId, drafts.value[key] ?? [], originals.get(key) ?? new Set(), entry.definition.setMembership)
      }
    }
    emit('saved')
  } catch { saveError.value = true } finally { saving.value = false }
}
onMounted(loadHumans)
</script>

<style scoped>
.team-editor { width: 1100px; max-width: 96vw; }
.team-editor-body { max-height: calc(90vh - 150px); overflow-y: auto; }
</style>
