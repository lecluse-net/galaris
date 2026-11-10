<template>
  <q-select ref="select" :model-value="$attrs.modelValue" :options="groupedOptions" emit-value map-options v-bind="$attrs"
    :use-input="false" :hide-selected="false" behavior="menu"
    @popup-show="showPopup" @popup-hide="hidePopup" @update:model-value="setQuery('')">
    <template v-for="(_, name) in forwardedSlots" #[name]="scope">
      <slot :name="name" v-bind="scope ?? {}" />
    </template>
    <template #before-options>
      <AgentSearchInput key="agent-search" ref="search" :model-value="query" @update:model-value="setQuery" @keydown="searchKeydown" />
    </template>
    <template #no-option>
      <AgentSearchInput key="agent-search" ref="search" :model-value="query" @update:model-value="setQuery" @keydown="searchKeydown" />
      <slot name="no-option" :search="query">
        <q-item><q-item-section>{{ t('agent.noSearchResults') }}</q-item-section></q-item>
      </slot>
    </template>
    <template #option="scope">
      <q-item-label v-if="scope.opt.teamHeading" header class="text-weight-bold" role="presentation">
        {{ scope.opt.teamHeading }}
      </q-item-label>
      <div :class="{ 'q-virtual-scroll--with-prev': scope.opt.teamHeading }">
        <slot name="option" v-bind="scope">
          <q-item v-bind="scope.itemProps" :aria-label="scope.opt.label">
            <q-item-section v-if="scope.opt.value !== null" avatar>
              <AgentAvatar :agent-id="scope.opt.value" :name="scope.opt.label" :has-avatar="scope.opt.hasAvatar" size="32px" />
            </q-item-section>
            <q-item-section>
              <q-item-label>{{ scope.opt.label }}</q-item-label>
              <q-item-label v-if="scope.opt.caption" caption>{{ scope.opt.caption }}</q-item-label>
            </q-item-section>
            <q-item-section v-if="$attrs.multiple !== undefined && scope.selected" side><q-icon name="check" color="primary" /></q-item-section>
          </q-item>
        </slot>
      </div>
    </template>
  </q-select>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, useAttrs, useSlots, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'
import type { QSelect } from 'quasar'
import AgentAvatar from './AgentAvatar.vue'
import AgentSearchInput from './AgentSearchInput.vue'
import { groupAgentOptions, type AgentChoice } from '../services/agentOptionGroups'
import type { AgentSelectionOption, AgentSelectionScope } from '../services/agentSelectionService'
import { useAgentTeamMetadata } from '../composables/useAgentTeamMetadata'

defineOptions({ inheritAttrs: false })
type FilterUpdate = (callback: () => void) => void
const { options, agents, scope = 'management', onFilter } = defineProps<{
  options: readonly AgentChoice[]
  agents?: readonly AgentSelectionOption[]
  scope?: AgentSelectionScope
  onFilter?: (value: string, update: FilterUpdate, abort: () => void) => void
}>()
const { t } = useI18n()
const attrs = useAttrs()
const slots = useSlots()
const forwardedSlots = computed(() => Object.fromEntries(Object.entries(slots).filter(([name]) => !['option', 'no-option', 'before-options'].includes(name))))
const { metadata, open, close } = useAgentTeamMetadata(() => scope, () => agents)
const query = ref('')
const select = useTemplateRef<QSelect>('select')
const search = useTemplateRef<InstanceType<typeof AgentSearchInput>>('search')
const normalize = (value: string) => value.normalize('NFD').replace(/\p{M}/gu, '').toLocaleLowerCase()
const groupedOptions = computed(() => groupAgentOptions(
  options.filter(option => normalize(option.label).includes(normalize(query.value.trim()))),
  agents ?? metadata.value, t('agent.noGroup'),
))
let filterVersion = 0
function setQuery(value: string): void {
  query.value = value
  const current = ++filterVersion
  const update: FilterUpdate = callback => {
    if (current === filterVersion) callback()
  }
  onFilter?.(value, update, () => {})
  select.value?.setOptionIndex(-1)
}
function showPopup(): void {
  setQuery('')
  void open()
  void nextTick(() => search.value?.focus())
}
function searchKeydown(event: KeyboardEvent): void {
  if (event.isComposing) return
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    event.preventDefault()
    event.stopPropagation()
    select.value?.moveOptionSelection(event.key === 'ArrowDown' ? 1 : -1)
  } else if (event.key === 'Enter') {
    event.preventDefault()
    event.stopPropagation()
    const index = select.value?.getOptionIndex() ?? -1
    const option = index >= 0 ? groupedOptions.value[index] : groupedOptions.value.find(option => !option.disable)
    if (option && !option.disable) {
      select.value?.toggleOption(option)
      if (attrs.multiple === undefined || attrs.multiple === false) select.value?.hidePopup()
    }
  } else if (event.key !== 'Escape' && event.key !== 'Tab') {
    event.stopPropagation()
  }
}
function hidePopup(): void { setQuery(''); close() }
</script>
