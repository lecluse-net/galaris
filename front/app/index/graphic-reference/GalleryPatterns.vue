<template>
  <div class="row q-col-gutter-lg">
    <div class="col-12 col-md-6">
      <q-toolbar class="pattern-toolbar"><q-icon name="folder" /><q-toolbar-title>{{ t('graphicReference.before') }}</q-toolbar-title></q-toolbar>
      <q-list bordered separator><q-item v-for="(tone, index) in ['active', 'success', 'neutral'] as const" :key="tone" clickable :active="selected === index" @click="selected = index"><q-item-section avatar><PersonAvatar :name="t('graphicReference.incoming')" /></q-item-section><q-item-section><q-item-label>{{ t('graphicReference.sample') }} {{ index + 1 }}</q-item-label><q-item-label caption>{{ t('graphicReference.paragraph') }}</q-item-label></q-item-section><q-item-section side><StatusBadge :tone="tone" :label="t(`graphicReference.${tone}`)" /></q-item-section></q-item></q-list>
      <q-pagination v-model="page" :max="5" class="q-mt-md" :aria-label="t('graphicReference.navigation')" />
      <q-btn-group outline class="q-mt-md"><q-btn v-for="key in ['first', 'second']" :key="key" outline :label="t(`graphicReference.${key}`)" @click="selected = selected === 0 ? 1 : 0" /></q-btn-group>
      <q-timeline color="primary"><q-timeline-entry :title="t('graphicReference.active')" icon="play_arrow">{{ t('graphicReference.message') }}</q-timeline-entry><q-timeline-entry :title="t('graphicReference.success')" icon="check">{{ t('graphicReference.details') }}</q-timeline-entry></q-timeline>
    </div>
    <div class="col-12 col-md-6">
      <q-stepper v-model="step" vertical color="primary" flat bordered><q-step :name="1" :title="t('graphicReference.first')" icon="edit" :done="step > 1">{{ t('graphicReference.details') }}<div class="q-mt-md"><q-btn color="primary" :label="t('graphicReference.second')" @click="step = 2" /></div></q-step><q-step :name="2" :title="t('graphicReference.second')" icon="check">{{ t('graphicReference.success') }}<div class="q-mt-md"><q-btn outline :label="t('graphicReference.first')" @click="step = 1" /></div></q-step></q-stepper>
      <q-scroll-area class="q-mt-md" style="height: 130px"><q-list><q-item v-for="index in 10" :key="index"><q-item-section>{{ t('graphicReference.sample') }} {{ index }}</q-item-section></q-item></q-list></q-scroll-area>
      <div class="relative-position q-mt-md q-pa-md pattern-loading"><q-toggle v-model="loading" :label="t('graphicReference.loading')" /><q-inner-loading :showing="loading" color="primary"><div class="row q-gutter-sm items-center"><q-spinner color="primary" /><q-btn outline :label="t('graphicReference.close')" @click="loading = false" /></div></q-inner-loading></div>
      <q-markup-table flat bordered class="q-mt-md"><thead><tr><th>{{ t('graphicReference.name') }}</th><th>{{ t('graphicReference.preview') }}</th></tr></thead><tbody><tr><td>{{ t('graphicReference.sample') }}</td><td>{{ selected + 1 }}</td></tr></tbody></q-markup-table>
    </div>
  </div>
</template>
<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { PersonAvatar, StatusBadge } from '@/core/util'
const { t } = useI18n()
const page = ref(1), step = ref(1), selected = ref(0), loading = ref(false)
</script>
<style scoped>
.pattern-toolbar { background: var(--solaire-blue-light); }
.pattern-loading { min-height: 70px; border: 1px solid var(--solaire-gray-accent); }
.body--dark .pattern-toolbar { background: var(--solaire-blue-dark); }
</style>
