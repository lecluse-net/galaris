<route lang="json">
{ "path": "/tool-inventory", "meta": { "devOnly": true } }
</route>

<template>
  <ToolInventory v-if="settings.is_dev" />
</template>

<script setup lang="ts">
import { ToolInventory } from '@/app/services'
import { settings } from '@/core/settings'
</script>
