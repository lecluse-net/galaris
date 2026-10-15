<route lang="json">
{ "path": "/memory/documents" }
</route>

<template><span /></template>

<script setup lang="ts">
import { definePage } from 'vue-router/experimental'

definePage({ redirect: '/documents' })
</script>
