<template>
  <q-input v-model="draft" label="Page draft" />
  <q-btn label="Toggle editor" @click="open = !open" />
  <Editor v-if="open" v-model="content" label="Source" language="json" />
  <output>{{ content }}</output>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { defineAsyncView } from '../../core/util/asyncView'

const { failOnce = false } = defineProps<{ failOnce?: boolean }>()
let attempts = 0
const Editor = defineAsyncView(() => {
  if (failOnce && attempts++ === 0) return Promise.reject(new Error('Transient loader failure'))
  return import('../../core/util/components/CodeEditor.vue')
})
const open = ref(true)
const draft = ref('Keep this draft')
const content = ref('{"existing":true}')
</script>
