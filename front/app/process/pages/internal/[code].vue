<template><q-page class="q-pa-md"><NativeProcessEditor :code="String(route.params.code)" /></q-page></template>
<script setup lang="ts">
import { useRoute } from 'vue-router'
import NativeProcessEditor from '../../components/NativeProcessEditor.vue'
const route = useRoute()
</script>
