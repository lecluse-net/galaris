<template>
  <q-page class="legal-page q-pa-md">
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
import legalFr from '../content/legal.fr.md?raw'
import legalEn from '../content/legal.en.md?raw'
import legalZh from '../content/legal.zh.md?raw'

const { locale } = useI18n()
const content = computed(() => locale.value === 'fr' ? legalFr : locale.value === 'zh' ? legalZh : legalEn)
</script>

<style scoped>
.legal-page {
  max-width: 800px;
  margin: 0 auto;
}

.content-wrapper {
  padding-bottom: 60px; /* Leave room for the fixed footer. */
}
</style>
