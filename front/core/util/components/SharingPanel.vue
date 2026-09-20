<template>
  <div @click="openMenu">
    <q-field outlined dense stack-label hide-bottom-space tag="div" :model-value="displayedGrants"
      :label="t('resourceSharing.title')" :readonly="!editable" :loading="busy" :error="error || null" no-error-icon
      :class="['sharing-panel', { 'sharing-panel-clickable': canOpen, 'q-field--focused': menuOpen, 'q-field--highlighted': menuOpen }]">
      <template #control="{ id }">
        <div :id="id" ref="sharingControl" class="sharing-values full-width no-outline"
          role="combobox" aria-haspopup="dialog" :aria-label="t('resourceSharing.title')"
          :aria-expanded="menuOpen" :aria-controls="popoverId" :aria-disabled="!state || !editable || busy" :tabindex="canOpen ? 0 : -1"
          @keydown.enter.self.prevent="openMenu" @keydown.space.self.prevent="openMenu"
          @keydown.down.self.prevent="openMenu" @keydown.esc.self.prevent="menuOpen = false">
          <div v-if="displayedGrants.length" class="sharing-grants" role="list" :aria-label="t('resourceSharing.sharedWith')">
            <q-chip v-for="grant in displayedGrants" :key="grant.key" dense class="sharing-grant" role="listitem"
              :icon="grant.recipient && grant.recipient.kind !== 'team' ? undefined : grant.icon"
              :removable="editable" :disable="busy"
              :remove-aria-label="t('resourceSharing.removeNamed', { name: grant.label })"
              @remove="remove(grant.recipient)">
              <slot v-if="grant.recipient && grant.recipient.kind !== 'team'" name="avatar" :recipient="grant.recipient" size="22px">
                <PersonAvatar :name="grant.label" :avatar-url="grant.recipient.avatar_url" size="22px" />
              </slot>
              <span class="ellipsis">{{ grant.label }}</span>
              <q-icon v-if="editable" :name="grant.can_write ? 'edit' : 'visibility'"
                class="q-chip__icon sharing-right-toggle cursor-pointer" role="button" aria-hidden="false"
                :tabindex="busy ? -1 : 0" :aria-disabled="busy" :aria-pressed="grant.can_write"
                :aria-label="t('resourceSharing.toggleRight', { name: grant.label })"
                @click.stop="setRight(grant.recipient, !grant.can_write)"
                @keydown.enter.stop.prevent="setRight(grant.recipient, !grant.can_write)"
                @keydown.space.stop.prevent="setRight(grant.recipient, !grant.can_write)">
                <q-tooltip>{{ t(grant.can_write ? 'resourceSharing.write' : 'resourceSharing.read') }} · {{ t('resourceSharing.toggleRight', { name: grant.label }) }}</q-tooltip>
              </q-icon>
              <q-icon v-else :name="grant.can_write ? 'edit' : 'visibility'" class="q-chip__icon" aria-hidden="false"
                :aria-label="t(grant.can_write ? 'resourceSharing.write' : 'resourceSharing.read')">
                <q-tooltip>{{ t(grant.can_write ? 'resourceSharing.write' : 'resourceSharing.read') }}</q-tooltip>
              </q-icon>
            </q-chip>
          </div>
          <span v-else-if="state" class="sharing-private">{{ t('resourceSharing.private') }}</span>
        </div>
      </template>
      <template v-if="editable && !busy" #append>
        <q-icon :name="$q.iconSet.arrow.dropdown" class="q-select__dropdown-icon"
          :class="{ 'rotate-180': menuOpen, 'sharing-arrow-disabled': !canOpen }" aria-hidden="true" @click.stop="openMenu" />
      </template>
      <q-menu v-if="state && editable" v-model="menuOpen" no-parent-event :offset="[0, 6]">
        <div :id="popoverId" class="sharing-popover" role="dialog" :aria-label="t('resourceSharing.addShare')" @click.stop>
          <div v-if="shortcuts.length" class="sharing-shortcuts">
            <div v-for="target in shortcuts" :key="target.value" class="sharing-shortcut"
              role="group" :aria-label="target.label">
              <q-icon :name="target.icon" size="20px" class="sharing-icon" />
              <span class="shortcut-label">{{ target.label }}</span>
              <div class="shortcut-actions">
                <q-btn v-for="write in [false, true]" :key="String(write)" outline dense no-caps
                  :icon="write ? 'edit' : 'visibility'" :label="t(write ? 'resourceSharing.write' : 'resourceSharing.read')"
                  :aria-label="t('resourceSharing.grantRight', { name: target.label, right: t(write ? 'resourceSharing.write' : 'resourceSharing.read') })"
                  :disable="busy || (target.value === 'groups' && !ownerGroupChoices(write).length)" @click="setShortcut(target.value, write)" />
              </div>
              <q-tooltip v-if="target.value === 'groups'">{{ missingOwnerGroups.map(group => group.label).join(', ') }}</q-tooltip>
            </div>
          </div>
          <q-separator v-if="shortcuts.length" />
          <SharingRecipients :options="available" :disabled="busy" @grant="setGrant">
            <template v-if="$slots.avatar" #avatar="avatarProps"><slot name="avatar" v-bind="avatarProps" /></template>
          </SharingRecipients>
        </div>
      </q-menu>
      <template #error>
        <div role="alert" @click.stop>
          {{ t('resourceSharing.error') }}
          <q-btn flat dense round icon="refresh" :aria-label="t('resourceSharing.reload')" :disable="busy" @click.stop="emit('reload')" />
        </div>
      </template>
    </q-field>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, useId, useTemplateRef, watch } from 'vue'
import { useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import type { SharingChoice, SharingDraft, SharingRecipient, SharingState } from '../sharing'
import SharingRecipients from './SharingRecipients.vue'
import PersonAvatar from './PersonAvatar.vue'

const props = withDefaults(defineProps<{
  state: SharingState | null
  editable: boolean
  loading?: boolean
  saving?: boolean
  error?: boolean
}>(), { loading: false, saving: false, error: false })
const emit = defineEmits<{ save: [draft: SharingDraft]; reload: [] }>()
const { t } = useI18n()
const $q = useQuasar()
const menuOpen = ref(false)
const sharingControl = useTemplateRef<HTMLElement>('sharingControl')
const popoverId = useId()
const busy = computed(() => props.loading || props.saving)
const publicWrite = computed(() => props.state?.level === 'public' ? props.state.can_write : null)
const canOpen = computed(() => Boolean(props.state && props.editable && !busy.value && publicWrite.value !== true))
const key = (value: SharingRecipient): string => `${value.kind}:${value.id}`
const icon = (kind: SharingRecipient['kind']): string => ({ team: 'groups', user: 'person', agent: 'smart_toy' })[kind]
const available = computed<SharingChoice[]>(() => {
  const state = props.state
  if (!state || publicWrite.value === true) return []
  const direct = new Set(state.grants.map(key))
  const groups = new Set(state.grants.filter(grant => grant.kind === 'team').map(grant => grant.id))
  const writableGroups = new Set(state.grants.filter(grant => grant.kind === 'team' && grant.can_write).map(grant => grant.id))
  return state.options.filter(option => !direct.has(key(option)) && (!state.owner || key(option) !== key(state.owner)))
    .map(option => ({
      ...option,
      can_grant_read: publicWrite.value === null && !(option.group_ids ?? []).some(id => groups.has(id)),
      can_grant_write: !(option.group_ids ?? []).some(id => writableGroups.has(id)),
    }))
    .filter(option => option.can_grant_read || option.can_grant_write)
})
const missingOwnerGroups = computed(() => available.value.filter(option => props.state?.owner_groups.some(group => key(group) === key(option))))
const shortcuts = computed(() => [
  ...(publicWrite.value === null ? [{ value: 'public' as const, label: t('resourceSharing.public'), icon: 'public' }] : []),
  ...(missingOwnerGroups.value.length ? [{ value: 'groups' as const, label: t('resourceSharing.groups'), icon: 'groups' }] : []),
])
const displayedGrants = computed(() => {
  const state = props.state
  if (!state) return []
  return [
    ...(state.level === 'public' ? [{ key: 'public', label: t('resourceSharing.public'), icon: 'public', can_write: state.can_write, recipient: null }] : []),
    ...state.grants.map(grant => ({ key: key(grant), label: grant.label, icon: icon(grant.kind), can_write: grant.can_write, recipient: grant })),
  ]
})
function openMenu(): void {
  if (canOpen.value && !menuOpen.value) {
    sharingControl.value?.focus()
    menuOpen.value = true
  }
}
function ownerGroupChoices(write: boolean): SharingChoice[] {
  return missingOwnerGroups.value.filter(group => write ? group.can_grant_write : group.can_grant_read)
}
function persist(grants: SharingRecipient[], globalWrite: boolean | null = publicWrite.value): void {
  if (busy.value || !props.editable) return
  emit('save', {
    level: globalWrite !== null ? 'public' : grants.some(grant => grant.kind === 'team') ? 'groups' : 'private',
    can_write: globalWrite ?? false,
    grants: grants.map(({ kind, id, can_write }) => ({ kind, id, can_write })),
  })
}
function setShortcut(target: 'public' | 'groups', write: boolean): void {
  if (!props.state) return
  if (target === 'public') { persist(write ? [] : props.state.grants.filter(grant => grant.can_write), write); return }
  if (ownerGroupChoices(write).length) persist([
    ...props.state.grants, ...ownerGroupChoices(write).map(group => ({ ...group, can_write: write })),
  ])
}
function setGrant(recipient: SharingRecipient, write: boolean): void {
  if (!props.state || !available.value.some(option => key(option) === key(recipient) && (write ? option.can_grant_write : option.can_grant_read))) return
  persist([...props.state.grants, { ...recipient, can_write: write }])
}
function remove(recipient: SharingRecipient | null): void {
  if (!props.state) return
  if (recipient) persist(props.state.grants.filter(grant => key(grant) !== key(recipient)))
  else persist(props.state.grants, null)
}
function setRight(recipient: SharingRecipient | null, write: boolean): void {
  if (!props.state) return
  if (!recipient) { persist(write ? [] : props.state.grants.filter(grant => grant.can_write), write); return }
  if (!write && publicWrite.value !== null) { remove(recipient); return }
  persist(props.state.grants.map(grant => key(grant) === key(recipient) ? { ...grant, can_write: write } : grant))
}
watch(publicWrite, write => { if (write === true) menuOpen.value = false })
</script>

<style scoped>
.sharing-panel-clickable :deep(.q-field__control) { cursor: pointer; }
.sharing-values, .sharing-shortcut { display: flex; align-items: center; gap: 4px; }
.sharing-values { flex-wrap: wrap; }
.sharing-private { font-size: 14px; }
.sharing-icon { color: var(--solaire-blue-accent); }
.sharing-arrow-disabled { opacity: .4; }
.sharing-popover { width: 430px; max-width: calc(100vw - 24px); }
.sharing-shortcuts { padding: 0 10px 8px; }
.sharing-shortcut { padding: 3px 0; }
.shortcut-label { flex: 1; min-width: 0; font-size: 13px; }
.shortcut-actions { display: flex; gap: 6px; }
.shortcut-actions .q-btn { padding: 3px 8px; font-size: 12px; }
.sharing-grants { display: contents; }
.sharing-grant :deep(.q-chip__content) { gap: 4px; }
.sharing-right-toggle { opacity: .6; }
.sharing-right-toggle:hover, .sharing-right-toggle:focus { opacity: 1; }
</style>
