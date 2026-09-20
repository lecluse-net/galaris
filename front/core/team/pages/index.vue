<template><q-page class="q-pa-md"><PageHeader icon="groups" :title="t('team.title')" :description="t('team.intro')" /><TeamManager /></q-page></template>
<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { PageHeader } from '@/core/util'
import TeamManager from '../components/TeamManager.vue'
const { t } = useI18n()
</script>
