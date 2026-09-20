<template>
  <UserMenu hide-profile-link>
    <template #prepend-menu>
      <RoleSwitcher />
      <q-separator />
      <q-item clickable v-close-popup to="/authorize/profile">
          <q-item-section avatar>
            <q-icon name="account_circle" />
          </q-item-section>
          <q-item-section>
            <q-item-label>{{ $t('authorize.roleSwitcher.myProfile') }}</q-item-label>
          </q-item-section>
      </q-item>
      <q-separator />
    </template>
  </UserMenu>
</template>

<script setup lang="ts">
import UserMenu from '@/core/user/components/UserMenu.vue'
import RoleSwitcher from './RoleSwitcher.vue'
</script>
