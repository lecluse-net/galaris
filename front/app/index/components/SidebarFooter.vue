<template>
  <footer class="sidebar-footer" :class="{ 'sidebar-footer--compact': compact }">
    <template v-if="!compact">
      <span class="sidebar-version" :title="version">{{ version }}</span>
      <span aria-hidden="true">|</span>
      <router-link to="/about" class="footer-link">{{ $t('nav.about') }}</router-link>
    </template>
    <q-btn v-else flat round dense size="sm" icon="info_outline" to="/about" :aria-label="$t('nav.about')">
      <q-tooltip>{{ version }} | {{ $t('nav.about') }}</q-tooltip>
    </q-btn>
  </footer>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { settings } from '@/core/settings'

defineProps<{ compact?: boolean }>()
const { t } = useI18n()
const version = computed(() => settings.APP_VERSION || t('index.about.unknownVersion'))
</script>

<style scoped>
.sidebar-footer {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  gap: 8px;
  padding: 10px 12px calc(10px + env(safe-area-inset-bottom, 0px));
  border-top: 1px solid var(--solaire-gray-light);
  color: var(--solaire-gray-accent);
  font-size: 11px;
}

body.body--dark .sidebar-footer {
  border-color: var(--solaire-gray-dark);
}

.sidebar-version {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.footer-link {
  flex-shrink: 0;
  color: inherit;
  text-decoration: none;
}

.footer-link:hover,
.footer-link:focus-visible {
  text-decoration: underline;
}

.sidebar-footer--compact {
  padding-inline: 4px;
}
</style>
