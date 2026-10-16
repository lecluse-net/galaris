<template><q-page class="q-pa-md"><PageHeader icon="account_tree" :title="t('nativeProcesses.runs')" /><NativeRunPanel :run-id="String(route.params.id)" /></q-page></template>
<script setup lang="ts">
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { PageHeader } from '@/core/util'
import NativeRunPanel from '../../../components/NativeRunPanel.vue'
const route = useRoute()
const { t } = useI18n()
</script>
