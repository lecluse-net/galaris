<template>
  <q-page class="license-page q-pa-md">
    <div class="content-wrapper">
      <q-card flat bordered class="q-pa-md">
        <q-card-section>
          <Markdown :content="content" />
        </q-card-section>
      </q-card>

      <div class="text-center q-mt-xl">
        <q-btn flat color="primary" to="/" icon="arrow_back" :label="$t('index.backHome')" />
      </div>
    </div>
  </q-page>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Markdown } from '@/core/util'
import licenseFr from '../content/license.fr.md?raw'
import licenseEn from '../content/license.en.md?raw'
import licenseZh from '../content/license.zh.md?raw'

const { locale } = useI18n()
const content = computed(() => locale.value === 'fr' ? licenseFr : locale.value === 'zh' ? licenseZh : licenseEn)
</script>

<style scoped>
.license-page {
  max-width: 800px;
  margin: 0 auto;
  min-height: calc(100vh - 50px); /* Full viewport height minus the footer. */
  display: flex;
  flex-direction: column;
}

.content-wrapper {
  flex: 1;
}
</style>
