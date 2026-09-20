<template>
  <q-page class="profile-page q-pa-sm">
    <PageHeader :icon="navigationIcon('people')" :title="$t('nav.profile')" :description="$t('nav.profile_desc')" />

    <div v-if="authStore.user" class="profile-content">
      <div class="profile-grid">
        <aside class="profile-identity">
          <ProfileIdentityCard
            :avatar-url="authStore.user.avatar_url"
            :display-name="authStore.user.display_name"
            :email="authStore.user.email"
            :role-label="defaultAssignment ? localizedAuthorizeLabel(defaultAssignment.role) : null"
            :loading="authStore.loading"
            @upload-avatar="handleAvatarSelected"
            @delete-avatar="handleAvatarDelete"
            @update-display-name="handleDisplayNameUpdate"
          >
            <template #identities>
              <component
                :is="component"
                v-for="(component, index) in identityComponents"
                :key="index"
              />
            </template>
          </ProfileIdentityCard>
        </aside>

        <section class="profile-security">
          <q-card flat bordered>
            <q-card-section class="row items-center q-gutter-sm">
              <q-icon name="security" color="primary" size="sm" />
              <div class="text-subtitle1 text-weight-medium">{{ $t('user.profile.securityTitle') }}</div>
            </q-card-section>

            <q-separator />

            <q-card-section>
              <PasswordSettingsForm
                :loading="authStore.loading"
                @update="handlePasswordUpdate"
              />
            </q-card-section>

            <q-separator />

            <MfaSettings embedded />
          </q-card>
        </section>

        <section class="profile-preferences">
          <q-card flat bordered>
            <q-card-section>
              <div class="row items-center q-gutter-sm">
                <q-icon name="tune" color="primary" size="sm" />
                <div class="text-subtitle1 text-weight-medium">{{ $t('user.profile.preferences') }}</div>
              </div>
            </q-card-section>

            <q-separator />

            <q-card-section class="row q-col-gutter-sm">
              <div class="col-12 col-sm-6">
                <q-select
                  v-model="currentLocale"
                  :options="localeOptions"
                  :label="$t('user.profile.language')"
                  :hint="$t('user.profile.languageHint')"
                  emit-value
                  map-options
                  outlined
                  dense
                >
                  <template #prepend>
                    <q-icon name="translate" />
                  </template>
                </q-select>
              </div>

              <div class="col-12 col-sm-6">
                <q-select
                  v-model="currentTheme"
                  :options="themeOptions"
                  :label="$t('user.profile.theme')"
                  :hint="$t('user.profile.themeHint')"
                  emit-value
                  map-options
                  outlined
                  dense
                >
                  <template #prepend>
                    <q-icon name="dark_mode" />
                  </template>
                </q-select>
              </div>
            </q-card-section>
          </q-card>
        </section>

        <section v-if="authorizeStore.assignments.length >= 2" class="profile-roles">
          <q-card flat bordered>
            <q-card-section>
              <div class="row items-center q-gutter-sm">
                <q-icon name="badge" color="primary" size="sm" />
                <div class="text-subtitle1 text-weight-medium">{{ $t('authorize.profile.myRoles') }}</div>
              </div>
              <div class="text-caption text-grey-7 q-mt-xs">
                {{ $t('authorize.profile.chooseDefault') }}
              </div>
            </q-card-section>

            <q-separator />

            <q-list separator>
              <q-item
                v-for="assignment in authorizeStore.assignments"
                :key="assignment.id"
                dense
                clickable
                @click="setDefault(assignment.id)"
              >
                <q-item-section avatar>
                  <q-icon
                    :name="assignment.is_default ? 'star' : 'star_border'"
                    :color="assignment.is_default ? 'amber-7' : 'grey'"
                  />
                </q-item-section>

                <q-item-section>
                  <q-item-label>{{ localizedAuthorizeLabel(assignment.role) }}</q-item-label>
                  <q-item-label caption>
                    {{ $t('authorize.codeLabel') }}: {{ assignment.role.code }}
                  </q-item-label>
                </q-item-section>

                <q-item-section side>
                  <q-chip
                    v-if="assignment.is_default"
                    color="primary"
                    text-color="white"
                    size="sm"
                    dense
                  >
                    {{ $t('authorize.profile.byDefault') }}
                  </q-chip>
                  <q-tooltip v-else>
                    {{ $t('authorize.profile.setDefault') }}
                  </q-tooltip>
                </q-item-section>
              </q-item>
            </q-list>
          </q-card>
        </section>
      </div>

      <div v-if="visibleProfileContributions.length" class="profile-contributions">
        <component
          :is="contribution.component"
          v-for="(contribution, index) in visibleProfileContributions"
          :key="index"
        />
      </div>

      <AccountDeletionCard
        :loading="authStore.loading"
        @delete="handleDelete"
      />
    </div>

    <div v-else class="text-center q-pa-lg">
      <q-spinner size="40px" color="primary" />
      <p>{{ $t('user.profile.loading') }}</p>
    </div>
  </q-page>
</template>

<script setup lang="ts">
import { navigationIcon } from '@/core/navigation'
import { computed, ref, watch } from 'vue'
import { useQuasar } from 'quasar'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/core/user/stores/authStore'
import { useAuthorizeStore } from '@/core/authorize/stores/authorizeStore'
import { usePrivilegeStore } from '@/core/authorize/stores/privilegeStore'
import { localizedAuthorizeLabel } from '@/core/authorize/presentation'
import { SUPPORTED_LOCALES, getLocale, type AppLocale } from '@/core/i18n'
import { getThemeMode, setThemeMode, type ThemeMode } from '@/core/theme'
import { PageHeader } from '@/core/util'
import {
  AccountDeletionCard,
  MfaSettings,
  PasswordSettingsForm,
} from '@/core/user'
import ProfileIdentityCard from '../components/ProfileIdentityCard.vue'
import { profileContributions } from '../profileContributions'

const authStore = useAuthStore()
const authorizeStore = useAuthorizeStore()
const privilegeStore = usePrivilegeStore()
const $q = useQuasar()
const router = useRouter()
const { t } = useI18n()

const localeOptions = SUPPORTED_LOCALES.map(locale => ({
  label: locale.label,
  value: locale.value,
}))

const currentLocale = computed<AppLocale>({
  get: () => (authStore.user?.language as AppLocale) || getLocale(),
  set: value => {
    void authStore.setLanguage(value)
  },
})

const themeOptions = computed(() => [
  { label: t('user.profile.themeAuto'), value: 'auto' },
  { label: t('user.profile.themeLight'), value: 'light' },
  { label: t('user.profile.themeDark'), value: 'dark' },
])

const currentTheme = ref<ThemeMode>(getThemeMode())
watch(currentTheme, mode => {
  setThemeMode(mode)
})

const defaultAssignment = computed(() =>
  authorizeStore.assignments.find(assignment => assignment.is_default),
)
const visibleProfileContributions = computed(() =>
  profileContributions.filter(
    contribution => !contribution.privilege
      || privilegeStore.hasPrivilege(contribution.privilege),
  ),
)
const identityComponents = computed(() =>
  visibleProfileContributions.value.flatMap(contribution =>
    contribution.identityComponent ? [contribution.identityComponent] : [],
  ),
)

async function setDefault(assignmentId: number): Promise<void> {
  try {
    await authorizeStore.setDefaultAssignment(assignmentId)
    $q.notify({
      type: 'positive',
      message: t('authorize.profile.defaultUpdated'),
    })
  } catch {
    $q.notify({
      type: 'negative',
      message: t('authorize.profile.updateError'),
    })
  }
}

async function handleAvatarSelected(file: File): Promise<void> {
  try {
    await authStore.uploadAvatar(file)
    notifySuccess('user.profile.avatarUpdated')
  } catch (error: unknown) {
    notifyError(error, 'user.profile.avatarUploadError')
  }
}

async function handleAvatarDelete(): Promise<void> {
  try {
    await authStore.deleteAvatar()
    notifySuccess('user.profile.avatarDeleted')
  } catch (error: unknown) {
    notifyError(error, 'user.profile.avatarDeleteError')
  }
}

async function handleDisplayNameUpdate(displayName: string): Promise<void> {
  try {
    await authStore.updateProfile({ display_name: displayName })
    notifySuccess('user.profile.identityUpdated')
  } catch (error: unknown) {
    notifyError(error, 'user.profile.updateError')
  }
}

async function handlePasswordUpdate(password: string): Promise<void> {
  try {
    await authStore.updateProfile({ password })
    notifySuccess('user.profile.passwordUpdated')
  } catch (error: unknown) {
    notifyError(error, 'user.profile.updateError')
  }
}

function notifySuccess(messageKey: string): void {
  $q.notify({
    type: 'positive',
    message: t(messageKey),
    position: 'top',
  })
}

function notifyError(error: unknown, fallbackKey: string): void {
  $q.notify({
    type: 'negative',
    message: typeof error === 'string' ? error : t(fallbackKey),
    position: 'top',
  })
}

async function handleDelete(): Promise<void> {
  try {
    await authStore.deleteAccount()
    notifySuccess('user.profile.accountDeleted')
    await router.push('/')
  } catch {
    notifyError(null, 'user.profile.accountDeleteError')
  }
}
</script>

<style scoped>
.profile-content {
  width: 100%;
  display: grid;
  gap: 12px;
}

.profile-grid,
.profile-contributions {
  display: contents;
}

.profile-grid > *,
.profile-contributions > * {
  min-width: 0;
}

.profile-grid > * {
  display: flex;
  flex-direction: column;
}

.profile-grid > * > :deep(.q-card) {
  flex: 1;
}

.profile-content :deep(.danger-card) {
  grid-column: 1 / -1;
}

.profile-content :deep(.q-card__section) {
  padding: 12px;
}

.profile-content :deep(.text-h6) {
  font-size: 1rem;
  line-height: 1.5;
}

.profile-content :deep(.q-field--with-bottom) {
  padding-bottom: 0;
}

.profile-content :deep(.q-field__bottom) {
  position: static;
  transform: none;
  min-height: 0;
  padding-top: 6px;
}

.profile-page :deep(.page-header__icon) {
  font-size: 36px;
}

.profile-page :deep(.page-header__title) {
  font-size: 1.5rem;
  line-height: 1.4;
}

.profile-page :deep(.page-header:first-child) {
  margin-top: 0;
}

.profile-page :deep(.page-header__description) {
  font-size: 0.875rem;
  margin-top: 0;
}

.profile-content :deep(.danger-card .q-card__section) {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  gap: 8px 12px;
  margin: 0;
}

.profile-content :deep(.danger-card .q-card__section > *) {
  margin: 0;
}

@media (max-width: 1023.98px) {
  .profile-content :deep(.danger-card .q-card__section) {
    grid-template-columns: auto minmax(0, 1fr);
  }

  .profile-content :deep(.danger-card .q-btn) {
    grid-column: 1 / -1;
  }
}

@media (min-width: 1024px) {
  .profile-content {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
