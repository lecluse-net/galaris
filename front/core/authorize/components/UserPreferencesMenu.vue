<template>
  <q-item-label header class="text-grey-8 q-pt-md">
    {{ t('user.profile.preferences') }}
  </q-item-label>
  <q-item clickable>
    <q-item-section avatar>
      <q-icon name="translate" />
    </q-item-section>
    <q-item-section>
      <q-item-label>{{ t('user.profile.language') }}</q-item-label>
    </q-item-section>
    <q-item-section side>
      <div class="row items-center no-wrap q-gutter-xs">
        <span class="text-caption">{{ currentLocaleLabel }}</span>
        <q-icon name="chevron_right" />
      </div>
    </q-item-section>

    <q-menu anchor="top end" self="top start">
      <q-list class="language-menu-list" style="min-width: 160px">
        <q-item
          v-for="option in localeOptions"
          :key="option.value"
          clickable
          v-close-popup
          @click="selectLanguage(option.value)"
        >
          <q-item-section>{{ option.label }}</q-item-section>
          <q-item-section side>
            <q-icon v-if="option.value === currentLocale" name="check" />
          </q-item-section>
        </q-item>
      </q-list>
    </q-menu>
  </q-item>

  <q-item>
    <q-item-section avatar>
      <q-icon name="dark_mode" />
    </q-item-section>
    <q-item-section>
      <q-item-label>{{ t('user.profile.theme') }}</q-item-label>
    </q-item-section>
    <q-item-section side>
      <q-btn-toggle
        :model-value="currentTheme"
        :options="themeOptions"
        dense
        unelevated
        rounded
        color="grey-3"
        text-color="grey-8"
        toggle-color="primary"
        toggle-text-color="white"
        @update:model-value="selectTheme"
      >
        <template #theme-auto>
          <q-icon name="brightness_auto" />
          <q-tooltip>{{ t('user.profile.themeAuto') }}</q-tooltip>
        </template>
        <template #theme-light>
          <q-icon name="light_mode" />
          <q-tooltip>{{ t('user.profile.themeLight') }}</q-tooltip>
        </template>
        <template #theme-dark>
          <q-icon name="dark_mode" />
          <q-tooltip>{{ t('user.profile.themeDark') }}</q-tooltip>
        </template>
      </q-btn-toggle>
    </q-item-section>
  </q-item>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/core/user'
import { SUPPORTED_LOCALES, getLocale, type AppLocale } from '@/core/i18n'
import { getThemeMode, setThemeMode, type ThemeMode } from '@/core/theme'

const authStore = useAuthStore()
const { t } = useI18n()

const localeOptions = SUPPORTED_LOCALES.map(locale => ({
  label: locale.label,
  value: locale.value,
}))
const currentLocale = computed<AppLocale>(() =>
  (authStore.user?.language as AppLocale) || getLocale(),
)
const currentLocaleLabel = computed(() =>
  localeOptions.find(option => option.value === currentLocale.value)?.label ?? currentLocale.value,
)
const themeOptions = computed(() => [
  {
    value: 'auto' as ThemeMode,
    slot: 'theme-auto',
    attrs: { 'aria-label': t('user.profile.themeAuto') },
  },
  {
    value: 'light' as ThemeMode,
    slot: 'theme-light',
    attrs: { 'aria-label': t('user.profile.themeLight') },
  },
  {
    value: 'dark' as ThemeMode,
    slot: 'theme-dark',
    attrs: { 'aria-label': t('user.profile.themeDark') },
  },
])
const currentTheme = ref<ThemeMode>(getThemeMode())

async function selectLanguage(locale: AppLocale): Promise<void> {
  await authStore.setLanguage(locale)
}

function selectTheme(mode: ThemeMode): void {
  currentTheme.value = mode
  setThemeMode(mode)
}
</script>

<style scoped>
.language-menu-list :deep(.q-item) {
  min-height: 40px;
  padding-top: 4px;
  padding-bottom: 4px;
}
</style>
