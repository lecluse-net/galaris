<template>
  <q-field outlined dense stack-label hide-bottom-space :model-value="model" :label="label || t('resourceOwner.title')"
    :readonly="readonly" :disable="disable" :loading="loading">
    <template #control>
      <div class="owner-select-control" role="combobox" :tabindex="readonly || disable ? -1 : 0"
        :aria-label="label || t('resourceOwner.title')" :aria-expanded="open" aria-haspopup="listbox"
        :aria-readonly="readonly" :aria-disabled="disable || loading" @click="show" @keydown.enter.prevent="show" @keydown.space.prevent="show" @keydown.down.prevent="show">
        <slot v-if="selected" name="avatar" :owner="selected" size="22px">
          <OwnerAvatar :owner="selected" size="22px" />
        </slot>
        <span class="ellipsis">{{ selected ? displayName(selected) : t(clearable ? 'resourceOwner.all' : 'resourceOwner.choose') }}</span>
      </div>
    </template>
    <template #append>
      <q-btn v-if="clearable && model && !readonly && !disable" flat round dense icon="close" :aria-label="t('resourceOwner.clear')" @click.stop="model = ''" />
      <q-icon name="arrow_drop_down" class="cursor-pointer" @click="show" />
    </template>
    <template #default>
      <q-menu v-model="open" no-parent-event fit anchor="bottom start" self="top start" max-height="440px" :disable="readonly || disable || loading" @before-show="reset">
        <div class="owner-select-menu">
          <q-input v-model="query" outlined dense autofocus clearable :label="t('resourceOwner.search')" class="q-ma-sm">
            <template #prepend><q-icon name="search" /></template>
          </q-input>
          <q-list role="listbox" :aria-label="label || t('resourceOwner.title')">
            <section v-for="team in teams" :key="team.key" role="group" :aria-label="team.label">
              <q-separator />
              <q-item-label header class="text-weight-bold">{{ team.label }}</q-item-label>
              <div v-for="group in team.groups" :key="group.key" role="group" :aria-label="t('resourceOwner.' + group.kind)">
                <q-item-label header class="q-pl-lg">{{ t('resourceOwner.' + group.kind) }}</q-item-label>
                <q-item v-for="option in group.visible" :key="ownerKey(option)" clickable role="option" :aria-label="displayName(option)"
                  :aria-selected="model === ownerKey(option)" class="q-pl-lg" @click="select(ownerKey(option))">
                  <q-item-section avatar>
                    <slot name="avatar" :owner="option" size="28px">
                      <OwnerAvatar :owner="option" size="28px" />
                    </slot>
                  </q-item-section>
                  <q-item-section><q-item-label>{{ displayName(option) }}</q-item-label><q-item-label v-if="option.subtitle || isMe(option)" caption>{{ option.subtitle || option.label }}</q-item-label></q-item-section>
                </q-item>
                <div v-if="group.items.length > 50" class="row items-center justify-between q-px-sm q-pb-sm" role="group" :aria-label="t('resourceOwner.teamPages', { team: team.label, type: t('resourceOwner.' + group.kind) })">
                  <q-select :model-value="sizes[group.key] ?? 50" :options="[10, 20, 50, 100, 500]" dense borderless :aria-label="t('resourceOwner.perPage')" @update:model-value="value => { sizes[group.key] = value; pages[group.key] = 1 }" />
                  <q-pagination :model-value="group.page" :max="group.pageCount" :max-pages="3" direction-links boundary-numbers size="sm" @update:model-value="value => { pages[group.key] = value }" />
                </div>
              </div>
            </section>
            <q-item v-if="!teams.length"><q-item-section>{{ t('resourceOwner.empty') }}</q-item-section></q-item>
          </q-list>
        </div>
      </q-menu>
    </template>
  </q-field>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import OwnerAvatar from './OwnerAvatar.vue'
import { ownerKey, type OwnerOption } from '../owners'
import { usePersonMemberships } from '@/core/util/facade'
import { groupOwnersByTeam } from '../ownerGroups'

const { options, current, currentUserId, label, readonly = false, disable = false, loading = false, clearable = false } = defineProps<{
  options: readonly OwnerOption[]; current?: OwnerOption | null; label?: string
  currentUserId?: number
  readonly?: boolean; disable?: boolean; loading?: boolean; clearable?: boolean
}>()
const model = defineModel<string>({ required: true })
const emit = defineEmits<{ open: [] }>()
const { t, locale } = useI18n()
const open = ref(false), query = ref<string | null>('')
const agentTeams = usePersonMemberships('agent'), userTeams = usePersonMemberships('user')
const pages = ref<Record<string, number>>({}), sizes = ref<Record<string, number>>({})
const isMe = (option: OwnerOption): boolean => option.kind === 'user' && (option.is_current_user === true || option.id === currentUserId)
const displayName = (option: OwnerOption): string => isMe(option) ? t('resourceOwner.me') : option.label
const normalize = (value: string): string => value.normalize('NFD').replace(/\p{M}/gu, '').toLocaleLowerCase(locale.value)
const matches = (option: OwnerOption): boolean => normalize(`${displayName(option)} ${option.label} ${option.subtitle ?? ''}`).includes(normalize(query.value ?? ''))
const selected = computed(() => options.find(option => ownerKey(option) === model.value) ?? (current && ownerKey(current) === model.value ? current : null))
const teams = computed(() => groupOwnersByTeam(
  options.filter(matches).sort((a, b) => Number(isMe(b)) - Number(isMe(a))
    || a.label.localeCompare(b.label, locale.value, { sensitivity: 'base' }) || a.id - b.id),
  { agent: agentTeams.members.value, user: userTeams.members.value }, t('agent.noGroup'),
).map(team => ({ ...team, groups: team.groups.map(group => {
  const size = sizes.value[group.key] ?? 50
  const pageCount = Math.max(1, Math.ceil(group.items.length / size))
  const page = Math.min(pages.value[group.key] ?? 1, pageCount)
  return { ...group, pageCount, page, visible: group.items.length > 50 ? group.items.slice((page - 1) * size, page * size) : group.items }
}) })))
function reset(): void { query.value = ''; pages.value = {}; void agentTeams.open(); void userTeams.open(); emit('open') }
function show(): void { if (!readonly && !disable && !loading) open.value = true }
function select(key: string): void { model.value = key; open.value = false }
watch(query, () => { pages.value = {} })
watch(() => options, () => { pages.value = {} })
watch(() => [readonly, disable], () => { if (readonly || disable) open.value = false })
watch(open, value => { if (!value) { agentTeams.close(); userTeams.close() } })
</script>

<style scoped>
.owner-select-control { display: flex; align-items: center; gap: 8px; width: 100%; min-width: 0; height: 100%; cursor: pointer; }
</style>
