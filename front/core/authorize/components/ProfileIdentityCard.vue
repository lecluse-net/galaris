<template>
  <q-card flat bordered>
    <q-card-section class="row items-center q-gutter-sm">
      <q-icon name="badge" color="primary" size="sm" />
      <div class="text-subtitle1 text-weight-medium">{{ t('user.profile.identityTitle') }}</div>
    </q-card-section>

    <q-separator />

    <q-card-section class="row items-center no-wrap q-gutter-sm">
      <q-avatar size="48px" color="primary" text-color="white" class="text-h6">
        <img
          v-if="avatarUrl && !avatarLoadFailed"
          :src="avatarUrl"
          :alt="t('user.avatar')"
          @error="avatarLoadFailed = true"
        />
        <template v-else>{{ initials }}</template>
      </q-avatar>

      <div class="col" style="min-width: 0">
        <div class="text-subtitle2 ellipsis">
          {{ identityLabel }}
        </div>
        <div class="row items-center no-wrap text-caption text-grey-7">
          <q-icon name="email" size="16px" class="q-mr-xs" />
          <span class="ellipsis">{{ email }}</span>
        </div>
        <q-chip v-if="roleLabel" dense outline color="primary" icon="badge" class="q-ma-none q-mt-xs">
          {{ roleLabel }}
        </q-chip>
      </div>
    </q-card-section>

    <q-separator />

    <q-card-section>
      <q-form class="row items-start q-col-gutter-sm" @submit.prevent="submitDisplayName">
        <q-input
          v-model="editedDisplayName"
          outlined
          dense
          class="col"
          :label="t('userEdit.displayName')"
          :hint="t('userEdit.displayNameHint')"
          :disable="loading"
        >
          <template #prepend>
            <q-icon name="person" />
          </template>
        </q-input>

        <div class="col-auto">
          <q-btn
            type="submit"
            color="primary"
            no-caps
            :label="t('common.save')"
            :loading="loading"
            :disable="!displayNameChanged"
          />
        </div>
      </q-form>
    </q-card-section>

    <q-separator />

    <q-card-section class="q-gutter-sm">
      <q-file
        v-model="avatarFile"
        dense
        outlined
        :label="t('user.profile.avatarUpload')"
        :hint="t('user.profile.avatarHint')"
        :max-file-size="AVATAR_MAX_BYTES"
        accept=".jpg,.jpeg,.png,.gif,.webp,image/jpeg,image/png,image/gif,image/webp"
        :loading="loading"
        :disable="loading"
        @update:model-value="handleAvatarSelected"
        @rejected="handleAvatarRejected"
      >
        <template #prepend>
          <q-icon name="cloud_upload" />
        </template>
      </q-file>
      <q-btn
        v-if="avatarUrl"
        flat
        dense
        no-caps
        color="negative"
        icon="delete"
        :label="t('user.profile.avatarDelete')"
        :loading="loading"
        @click="emit('deleteAvatar')"
      />
    </q-card-section>
    <slot name="identities" />
  </q-card>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useQuasar, type QRejectedEntry } from 'quasar'
import { useI18n } from 'vue-i18n'

const {
  avatarUrl = null,
  displayName = null,
  email,
  roleLabel = null,
  loading = false,
} = defineProps<{
  avatarUrl?: string | null
  displayName?: string | null
  email: string
  roleLabel?: string | null
  loading?: boolean
}>()
const emit = defineEmits<{
  uploadAvatar: [file: File]
  deleteAvatar: []
  updateDisplayName: [displayName: string]
}>()

const AVATAR_MAX_BYTES = 5_000_000
const $q = useQuasar()
const { t } = useI18n()
const avatarFile = ref<File | null>(null)
const avatarLoadFailed = ref(false)
const editedDisplayName = ref(displayName ?? '')
const identityLabel = computed(() => editedDisplayName.value.trim() || email)
const displayNameChanged = computed(
  () => editedDisplayName.value.trim() !== (displayName ?? '').trim(),
)
const initials = computed(() => {
  const name = identityLabel.value.trim()
  const parts = name.split(/\s+/)
  return `${parts[0]?.[0] ?? ''}${parts[1]?.[0] ?? ''}`.toUpperCase()
})

watch(() => avatarUrl, () => {
  avatarLoadFailed.value = false
})

watch(() => displayName, value => {
  editedDisplayName.value = value ?? ''
})

function submitDisplayName(): void {
  if (!displayNameChanged.value) return
  emit('updateDisplayName', editedDisplayName.value.trim())
}

function handleAvatarSelected(file: File | null): void {
  if (file === null) return
  emit('uploadAvatar', file)
  avatarFile.value = null
}

function handleAvatarRejected(_entries: QRejectedEntry[]): void {
  $q.notify({
    type: 'negative',
    message: t('user.profile.avatarRejected'),
    position: 'top',
  })
}
</script>
