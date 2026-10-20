<template>
  <q-btn outline label="Actions">
    <q-menu><q-list role="menu" aria-label="Root">
      <q-item clickable role="menuitem" aria-label="First" :disable="disabled"><q-item-section>First</q-item-section>
        <ContextSubmenu><q-list role="menu" aria-label="First options">
          <q-item clickable role="menuitem" aria-label="Nested"><q-item-section>Nested</q-item-section>
            <ContextSubmenu><q-list role="menu" aria-label="Nested options">
              <q-item clickable role="menuitem" v-close-popup @click="count++"><q-item-section>Apply</q-item-section></q-item>
            </q-list></ContextSubmenu>
          </q-item>
        </q-list></ContextSubmenu>
      </q-item>
      <q-item clickable role="menuitem" aria-label="Second"><q-item-section>Second</q-item-section>
        <ContextSubmenu><q-list role="menu" aria-label="Second options">
          <q-item clickable role="menuitem"><q-item-section>Other action</q-item-section></q-item>
        </q-list></ContextSubmenu>
      </q-item>
      <q-item clickable role="menuitem" aria-label="Leaf"><q-item-section>Leaf</q-item-section></q-item>
    </q-list></q-menu>
  </q-btn>
  <p role="status">{{ count }}</p>
</template>
<script setup lang="ts">
import { ref } from 'vue'
import ContextSubmenu from '@/core/util/components/ContextSubmenu.vue'
defineProps<{ disabled?: boolean }>()
const count = ref(0)
</script>
