<template>
  <div v-if="compact" class="row items-center q-gutter-sm">
    <q-badge color="primary" :label="selectedMembers.length" />
    <template v-if="selectedMembers.length <= 3">
      <span v-for="member in selectedMembers" :key="member.id" class="row items-center no-wrap q-gutter-xs">
        <AgentAvatar :agent-id="member.id" :name="member.label" :has-avatar="member.has_avatar" size="28px" />
        <span>{{ member.label }}</span>
      </span>
    </template>
  </div>
  <section v-else :aria-label="t('team.agents')">
    <div class="text-subtitle1 q-mb-md">{{ t('team.agents') }} <q-badge color="primary" :label="model.length" /></div>
    <div v-if="!readonly" class="row items-start no-wrap q-gutter-sm q-mb-md">
      <AgentTeamSelect v-if="multiple" v-model="selectedMany" class="col" outlined dense clearable use-input scope="teams"
        multiple use-chips emit-value map-options :options="options" :label="t('team.addAgent')" :disable="disabled"
        input-debounce="0" @filter="filter">
        <template #no-option><q-item><q-item-section>{{ t('common.noResults') }}</q-item-section></q-item></template>
        <template #option="scope">
          <q-item v-bind="scope.itemProps" :aria-label="scope.opt.label">
            <q-item-section avatar><AgentAvatar :agent-id="scope.opt.value" :name="scope.opt.label" :has-avatar="scope.opt.hasAvatar" /></q-item-section>
            <q-item-section><q-item-label>{{ scope.opt.label }}</q-item-label></q-item-section>
            <q-item-section side><q-icon v-if="scope.selected" name="check" color="primary" /></q-item-section>
          </q-item>
        </template>
      </AgentTeamSelect>
      <AgentSelect v-else v-model="selected" class="col" outlined dense clearable use-input
        :options="options" scope="teams" :load-agents="false" :label="t('team.addAgent')" :disable="disabled"
        input-debounce="0" @filter="filter" />
      <q-btn color="primary" icon="add" :label="t('team.add')" :disable="(multiple ? !selectedMany?.length : selected === null) || disabled" @click="add" />
    </div>
    <q-list bordered separator class="rounded-borders">
      <q-item v-for="member in selectedMembers" :key="member.id">
        <q-item-section avatar><AgentAvatar :agent-id="member.id" :name="member.label" :has-avatar="member.has_avatar" /></q-item-section>
        <q-item-section>{{ member.label }}</q-item-section>
        <q-item-section v-if="!readonly" side>
          <q-btn flat round dense icon="close" :disable="disabled" :aria-label="t('team.removeNamed', { name: member.label })"
            @click="model = model.filter(id => id !== member.id)" />
        </q-item-section>
      </q-item>
      <q-item v-if="!selectedMembers.length"><q-item-section class="text-grey-7">{{ t('team.empty') }}</q-item-section></q-item>
    </q-list>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import type { TeamMember } from '@/core/team'
import AgentAvatar from './AgentAvatar.vue'
import AgentSelect from './AgentSelect.vue'
import AgentTeamSelect from './AgentTeamSelect.vue'

const { members, readonly = false, disabled = false, compact = false, multiple = false } = defineProps<{
  members: TeamMember[]
  readonly?: boolean
  disabled?: boolean
  compact?: boolean
  multiple?: boolean
}>()
const model = defineModel<number[]>({ required: true })
const { t } = useI18n()
const selected = ref<number | null>(null)
const selectedMany = ref<number[] | null>([])
const query = ref('')
const selectedMembers = computed(() => members.filter(member => model.value.includes(member.id)))
const options = computed(() => members
  .filter(member => !model.value.includes(member.id) && member.label.toLocaleLowerCase().includes(query.value))
  .map(member => ({ value: member.id, label: member.label, hasAvatar: member.has_avatar })))
function filter(value: string, update: (callback: () => void) => void): void {
  update(() => { query.value = value.toLocaleLowerCase() })
}
function add(): void {
  if (readonly || disabled) return
  const requested = multiple ? selectedMany.value ?? [] : selected.value === null ? [] : [selected.value]
  const eligible = new Set(members.map(member => member.id))
  model.value = [...new Set([...model.value, ...requested.filter(id => eligible.has(id))])]
  selected.value = null
  selectedMany.value = []
  query.value = ''
}
</script>
