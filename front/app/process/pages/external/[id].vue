<template><q-page class="q-pa-md"><ExternalProcessEditor :id="Number(route.params.id)" /></q-page></template>
<script setup lang="ts">
import { useRoute } from 'vue-router'
import ExternalProcessEditor from '../../components/ExternalProcessEditor.vue'
const route = useRoute()
</script>
