<template>
  <q-page class="about-page q-pa-md">
    <q-card flat bordered>
      <q-card-section>
        <h1 class="text-h5 q-mt-none">{{ $t('nav.about') }}</h1>
        <p class="text-h6 q-mb-sm">{{ settings.APP_LABEL }}</p>
        <p>{{ $t('index.about.description') }}</p>
        <p class="text-caption">{{ $t('index.about.version', { version }) }}</p>
        <a href="https://lecluse.net" target="_blank" rel="noopener noreferrer" class="author-link">
          {{ $t('index.about.copyright') }}
        </a>
      </q-card-section>
      <q-separator />
      <q-card-actions>
        <q-btn flat color="primary" to="/license" :label="$t('nav.license')" />
      </q-card-actions>
    </q-card>
    <div class="text-center q-mt-xl">
      <q-btn flat color="primary" to="/" icon="arrow_back" :label="$t('index.backHome')" />
    </div>
  </q-page>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { settings } from '@/core/settings'

const { t } = useI18n()
const version = computed(() => settings.APP_VERSION || t('index.about.unknownVersion'))
</script>

<style scoped>
.about-page {
  max-width: 800px;
  margin: 0 auto;
  overflow-wrap: anywhere;
}

.author-link {
  color: inherit;
}
</style>
