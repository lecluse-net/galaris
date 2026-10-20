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
            <q-item v-if="me" clickable role="option" :aria-label="t('resourceOwner.me')" :aria-selected="model === ownerKey(me)" @click="select(ownerKey(me))">
              <q-item-section avatar><OwnerAvatar :owner="me" size="28px" /></q-item-section>
              <q-item-section><q-item-label>{{ t('resourceOwner.me') }}</q-item-label><q-item-label caption>{{ me.label }}</q-item-label></q-item-section>
            </q-item>
            <template v-for="group in groups" :key="group.kind">
              <q-separator v-if="group.items.length" />
              <q-item-label v-if="group.items.length" header>{{ t('resourceOwner.' + group.kind) }}</q-item-label>
              <q-item v-for="option in group.visible" :key="ownerKey(option)" clickable role="option" :aria-label="option.label"
                :aria-selected="model === ownerKey(option)" @click="select(ownerKey(option))">
                <q-item-section avatar>
                  <slot name="avatar" :owner="option" size="28px">
                    <OwnerAvatar :owner="option" size="28px" />
                  </slot>
                </q-item-section>
                <q-item-section><q-item-label>{{ option.label }}</q-item-label><q-item-label v-if="option.subtitle" caption>{{ option.subtitle }}</q-item-label></q-item-section>
              </q-item>
              <div v-if="group.items.length > 50" class="row items-center justify-between q-px-sm q-pb-sm" role="group" :aria-label="t('resourceOwner.pages', { type: t('resourceOwner.' + group.kind) })">
                <q-select v-model="sizes[group.kind]" :options="[10, 20, 50, 100, 500]" dense borderless :aria-label="t('resourceOwner.perPage')" @update:model-value="pages[group.kind] = 1" />
                <q-pagination v-model="pages[group.kind]" :max="group.pageCount" :max-pages="3" direction-links boundary-numbers size="sm" />
              </div>
            </template>
            <q-item v-if="!me && !groups.some(group => group.items.length)"><q-item-section>{{ t('resourceOwner.empty') }}</q-item-section></q-item>
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

const { options, current, currentUserId, label, readonly = false, disable = false, loading = false, clearable = false } = defineProps<{
  options: readonly OwnerOption[]; current?: OwnerOption | null; label?: string
  currentUserId?: number
  readonly?: boolean; disable?: boolean; loading?: boolean; clearable?: boolean
}>()
const model = defineModel<string>({ required: true })
const emit = defineEmits<{ open: [] }>()
const { t, locale } = useI18n()
const open = ref(false), query = ref<string | null>('')
const pages = ref({ user: 1, agent: 1 }), sizes = ref({ user: 50, agent: 50 })
const isMe = (option: OwnerOption): boolean => option.kind === 'user' && (option.is_current_user === true || option.id === currentUserId)
const displayName = (option: OwnerOption): string => isMe(option) ? t('resourceOwner.me') : option.label
const normalize = (value: string): string => value.normalize('NFD').replace(/\p{M}/gu, '').toLocaleLowerCase(locale.value)
const matches = (option: OwnerOption): boolean => normalize(`${displayName(option)} ${option.label} ${option.subtitle ?? ''}`).includes(normalize(query.value ?? ''))
const selected = computed(() => options.find(option => ownerKey(option) === model.value) ?? (current && ownerKey(current) === model.value ? current : null))
const me = computed(() => options.find(option => isMe(option) && matches(option)))
const groups = computed(() => (['user', 'agent'] as const).map(kind => {
  const items = options.filter(option => option.kind === kind && !isMe(option) && matches(option))
    .sort((a, b) => a.label.localeCompare(b.label, locale.value, { sensitivity: 'base' }) || a.id - b.id)
  const pageCount = Math.max(1, Math.ceil(items.length / sizes.value[kind]))
  const page = Math.min(pages.value[kind], pageCount)
  return { kind, items, pageCount, visible: items.length > 50 ? items.slice((page - 1) * sizes.value[kind], page * sizes.value[kind]) : items }
}))
function reset(): void { query.value = ''; pages.value = { user: 1, agent: 1 }; emit('open') }
function show(): void { if (!readonly && !disable && !loading) open.value = true }
function select(key: string): void { model.value = key; open.value = false }
watch(query, () => { pages.value = { user: 1, agent: 1 } })
watch(() => options, () => { pages.value = { user: 1, agent: 1 } })
watch(() => [readonly, disable], () => { if (readonly || disable) open.value = false })
</script>

<style scoped>
.owner-select-control { display: flex; align-items: center; gap: 8px; width: 100%; min-width: 0; height: 100%; cursor: pointer; }
</style>
