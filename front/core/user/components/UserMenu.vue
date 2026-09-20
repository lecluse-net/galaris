<template>
  <div v-if="authStore.isAuthenticated" class="user-menu-wrapper cursor-pointer">
    <q-tooltip>{{ $t('user.openMenuHint') }}</q-tooltip>
    <q-menu class="user-menu-popup" anchor="bottom end" self="top end">
      <q-list class="user-menu-list">
        <div class="user-menu-section user-menu-section--account">
          <q-item-label header class="text-grey-8 q-pt-md">
            {{ $t('user.myAccount') }}
          </q-item-label>
          <q-item clickable v-close-popup to="/authorize/profile">
            <q-item-section avatar>
              <q-icon name="person" />
            </q-item-section>
            <q-item-section>
              <q-item-label>{{ $t('nav.profile') }}</q-item-label>
            </q-item-section>
          </q-item>
          <q-item clickable v-close-popup to="/user/tokens">
            <q-item-section avatar>
              <q-icon name="vpn_key" />
            </q-item-section>
            <q-item-section>
              <q-item-label>{{ $t('nav.apiTokens') }}</q-item-label>
            </q-item-section>
          </q-item>
        </div>

        <q-separator class="user-menu-divider" />

        <div class="user-menu-section user-menu-section--preferences">
          <UserPreferencesMenu />
        </div>

        <q-separator class="user-menu-divider" />

        <div class="user-menu-section user-menu-section--assignments">
          <q-item-label header class="text-grey-8 q-pt-md">
            {{ $t('user.myAssignments') }}
          </q-item-label>
          <q-item
            v-for="assignment in authorizeStore.assignments"
            :key="assignment.id"
            clickable
            v-close-popup
            :class="{ 'user-menu-item--active': isCurrentAssignment(assignment.role_id) }"
            @click="switchToAssignment(assignment.role_id)"
          >
            <q-item-section avatar>
              <q-icon
                :name="isCurrentAssignment(assignment.role_id) ? 'radio_button_checked' : 'radio_button_unchecked'"
                class="assignment-icon"
                :class="{ 'assignment-icon--active': isCurrentAssignment(assignment.role_id) }"
              />
            </q-item-section>
            <q-item-section>
              <q-item-label>{{ localizedAuthorizeLabel(assignment.role) }}</q-item-label>
            </q-item-section>
            <q-item-section v-if="assignment.is_default" side>
              <q-badge color="positive" text-color="white" :label="$t('user.default')" />
            </q-item-section>
          </q-item>
        </div>

        <q-separator class="user-menu-divider" />

        <q-item class="user-menu-logout" clickable v-close-popup @click="handleLogout">
          <q-item-section avatar>
            <q-icon name="logout" />
          </q-item-section>
          <q-item-section>
            <q-item-label>{{ $t('user.logout') }}</q-item-label>
          </q-item-section>
        </q-item>
      </q-list>
    </q-menu>
    <div class="user-info-display">
      <div class="user-name">{{ authStore.userDisplayName }}</div>
      <div v-if="authorizeStore.roleLabel" class="user-role">
        <q-icon name="badge" size="xs" class="q-mr-xs" />
        {{ authorizeStore.roleLabel }}
      </div>
    </div>
    <q-btn
      v-if="!avatarUrl || avatarLoadFailed"
      fab
      color="primary"
      icon="account_circle"
      :aria-label="$t('user.myAccount')"
    />
    <div v-else class="avatar-container">
      <img
        :src="avatarUrl"
        :alt="authStore.userDisplayName || $t('user.avatar')"
        class="user-avatar-img"
        @error="avatarLoadFailed = true"
      />
    </div>
  </div>
  <div v-else class="user-menu-container">
    <LoginButton
      fab
      color="primary"
      icon="login"
      :label="$t('user.login')"
      :aria-label="$t('user.login')"
    >
      <q-tooltip>{{ $t('user.login') }}</q-tooltip>
    </LoginButton>
  </div>
</template>

<script setup lang="ts">
import { showConfirmationDialog } from '@/core/util'
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '../stores/authStore'
import LoginButton from './LoginButton.vue'
import { localizedAuthorizeLabel, UserPreferencesMenu, useAuthorizeStore } from '@/core/authorize'

const router = useRouter()
const $q = useQuasar()
const { t } = useI18n()
const authStore = useAuthStore()
const authorizeStore = useAuthorizeStore()
const avatarUrl = computed(() => authStore.user?.avatar_url ?? null)
const avatarLoadFailed = ref(false)

watch(avatarUrl, () => {
  avatarLoadFailed.value = false
})

function isCurrentAssignment(roleId: number): boolean {
  return authorizeStore.activeRole?.id === roleId
}

async function switchToAssignment(roleId: number): Promise<void> {
  if (isCurrentAssignment(roleId)) return

  try {
    await authorizeStore.switchRole(roleId)
    $q.notify({
      type: 'positive',
      message: t('user.roleChanged'),
      position: 'top',
    })
  } catch {
    $q.notify({
      type: 'negative',
      message: t('user.roleChangeError'),
      position: 'top',
    })
  }
}

async function handleLogout(): Promise<void> {
  showConfirmationDialog({
    title: t('user.logout'),
    message: t('user.logoutConfirm'),
    cancel: true,
  }).onOk(async () => {
    try {
      await authStore.logout()
      $q.notify({
        type: 'positive',
        message: t('user.logoutSuccess'),
        position: 'top',
      })
      await router.push('/')
    } catch {
      $q.notify({
        type: 'negative',
        message: t('user.logoutError'),
        position: 'top',
      })
    }
  })
}
</script>

<style scoped>
.user-menu-wrapper {
  display: flex;
  align-items: center;
  gap: 8px;
  background-color: #1976D2;
  padding: 0 0 0 16px;
  border-radius: 28px;
  height: 56px;
  box-sizing: border-box;
  transition: background-color 0.2s ease;
}

.user-menu-wrapper:hover {
  background-color: #1565C0;
}

.user-menu-wrapper:active {
  background-color: #0D47A1;
}

.user-menu-list :deep(.q-item__section--avatar) {
  min-width: 36px;
  padding-right: 10px;
}

:global(.user-menu-popup) {
  overflow: hidden;
  border: 1px solid rgba(30, 64, 104, 0.14);
  border-radius: 18px;
  background: transparent;
  box-shadow: 0 20px 54px rgba(15, 35, 62, 0.24);
}

.user-menu-list {
  --user-menu-hover: rgba(47, 68, 94, 0.07);
  width: 320px;
  max-width: calc(100vw - 24px);
  padding: 8px;
  color: #24364c;
  background: rgba(255, 255, 255, 0.98);
}

.user-menu-section :deep(.q-item),
.user-menu-logout {
  min-height: 44px;
  padding: 6px 10px;
  border-radius: 10px;
  transition: background-color 150ms ease, transform 150ms ease;
}

.user-menu-section :deep(.q-item:hover),
.user-menu-section :deep(.q-item:focus-visible),
.user-menu-section :deep(.user-menu-item--active),
.user-menu-logout:hover,
.user-menu-logout:focus-visible {
  background: var(--user-menu-hover);
}

.user-menu-section :deep(.q-item:focus-visible),
.user-menu-logout:focus-visible {
  outline: 2px solid currentColor;
  outline-offset: -2px;
}

.assignment-icon:not(.assignment-icon--active) {
  opacity: 0.42;
}

.user-menu-divider {
  margin: 6px 10px;
  background: rgba(47, 68, 94, 0.11);
}

body.body--dark .user-menu-list {
  --user-menu-hover: rgba(217, 225, 235, 0.08);
  color: #edf2f7;
  background: rgba(31, 35, 43, 0.99);
}

body.body--dark .user-menu-divider {
  background: rgba(217, 225, 235, 0.12);
}

.user-menu-wrapper .user-name,
.user-menu-wrapper .user-role {
  color: white;
}

.user-info-display {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  line-height: 1.2;
}

.user-name {
  font-weight: 600;
  font-size: 14px;
  color: inherit;
}

.user-role {
  font-size: 12px;
  opacity: 0.9;
  display: flex;
  align-items: center;
}

.avatar-container {
  position: relative;
  width: 56px;
  height: 56px;
  cursor: pointer;
  border-radius: 50%;
  transition: filter 0.2s ease;
}

.avatar-container:hover {
  filter: brightness(1.2);
}

.avatar-container:active {
  filter: brightness(0.9);
}

.user-avatar-img {
  width: 56px;
  height: 56px;
  object-fit: cover;
  border-radius: 50%;
  display: block;
}

.user-menu-container {
  display: flex;
  align-items: center;
}

@media (prefers-reduced-motion: reduce) {
  .user-menu-section :deep(.q-item),
  .user-menu-logout {
    transition: none;
  }
}
</style>
