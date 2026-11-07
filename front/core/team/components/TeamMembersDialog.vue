<template>
  <q-dialog v-model="open">
    <TeamEditor v-if="team && !loading && !error" :key="team.id" :team="team" :contributions="contributions"
      members-only @close="open = false" @saved="open = false" @changed="emit('changed')" />
    <q-card v-else class="galaris-dialog-card" style="width: 600px; max-width: 96vw">
      <q-card-section class="galaris-dialog-title row items-center">
        <div class="text-h6">{{ t('team.addMembers') }}</div><q-space />
        <q-btn v-close-popup flat round dense icon="close" :aria-label="t('common.close')" />
      </q-card-section>
      <q-card-section class="galaris-dialog-body">
        <q-linear-progress v-if="loading" indeterminate />
        <q-banner v-else role="alert">
          {{ t('team.error') }}
          <template #action><q-btn outline color="primary" :label="t('team.retry')" @click="load" /></template>
        </q-banner>
      </q-card-section>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { usePrivilegeStore } from '@/core/authorize'
import { teamService, type Team } from '../services/teamService'
import { teamContributions, type LoadedTeamContribution } from '../contributions'
import TeamEditor from './TeamEditor.vue'

const { teamId } = defineProps<{ teamId: number | null }>()
const open = defineModel<boolean>({ required: true })
const emit = defineEmits<{ changed: [] }>()
const { t } = useI18n()
const privileges = usePrivilegeStore()
const team = ref<Team>()
const contributions = shallowRef<LoadedTeamContribution[]>([])
const loading = ref(false)
const error = ref(false)
let generation = 0

async function load(): Promise<void> {
  if (teamId === null || !privileges.hasPrivilege('TEAM_ACCESS') || !privileges.hasPrivilege('TEAM_MEMBERS_EDIT')) return
  const current = ++generation
  const targetId = teamId
  loading.value = true
  error.value = false
  try {
    const [rows, entries] = await Promise.all([
      teamService.list(),
      Promise.all(teamContributions.filter(item => privileges.hasPrivilege(item.privilege))
        .map(async definition => ({ definition, members: await definition.load() }))),
    ])
    if (current !== generation) return
    const currentTeam = rows.find(row => row.id === targetId)
    if (!currentTeam) throw new Error('Team unavailable')
    team.value = currentTeam
    contributions.value = entries
  } catch {
    if (current === generation) error.value = true
  } finally {
    if (current === generation) loading.value = false
  }
}

watch(() => [open.value, teamId] as const, ([visible]) => {
  generation++
  team.value = undefined
  contributions.value = []
  if (visible) void load()
}, { immediate: true })
onBeforeUnmount(() => { generation++ })
</script>
