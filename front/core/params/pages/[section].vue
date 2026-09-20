<template>
  <PreferencesSectionPage v-if="section" :section="section.key" />
</template>

<script setup lang="ts">
import { computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import PreferencesSectionPage from '../components/PreferencesSectionPage.vue'
import { findPreferenceSectionBySlug } from '../presentation'

const route = useRoute()
const router = useRouter()
const section = computed(() => findPreferenceSectionBySlug(String(route.params.section ?? '')))

watch(() => String(route.params.section ?? ''), slug => {
  if (slug === 'drivers') {
    void router.replace('/params/harnesses')
    return
  }
  if (!findPreferenceSectionBySlug(slug)) void router.replace('/params')
}, { immediate: true })
</script>
