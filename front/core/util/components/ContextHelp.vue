<template>
  <aside v-if="store && visible" class="context-help" :aria-label="t('contextHelp.label')">
    <q-icon name="lightbulb_outline" size="24px" class="context-help__icon" aria-hidden="true" />
    <div class="context-help__content">
      <template v-if="store.ready">
        <p class="q-my-xs"><slot>{{ text }}</slot></p>
        <p v-if="store.saveErrors.includes(helpKey)" role="alert" class="q-my-xs">{{ t('contextHelp.saveError') }}</p>
        <q-btn unelevated no-caps class="context-help__confirm q-mt-sm" :label="t('contextHelp.understood')" :loading="saving" @click="store.dismiss(helpKey)" />
      </template>
      <template v-else>
        <p role="alert" class="q-my-xs">{{ t('contextHelp.loadError') }}</p>
        <q-btn flat no-caps :label="t('contextHelp.retry')" @click="store.load()" />
      </template>
    </div>
    <q-btn v-if="store.ready" flat round dense icon="close" :disable="saving"
      :aria-label="t('contextHelp.dismiss')" @click="store.dismiss(helpKey)" />
  </aside>
</template>

<script setup lang="ts">
import { computed, inject, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { contextHelpKey } from '../contextHelp'
import '../solaireTheme'

const props = defineProps<{ helpKey: string; text?: string }>()
const { t } = useI18n()
const store = inject(contextHelpKey)
const saving = computed(() => store?.pending.includes(props.helpKey) ?? false)
const visible = computed(() => store?.accountId != null && !store.dismissed.includes(props.helpKey)
  && (store.ready || store.loadError))

watch(() => [store?.accountId, props.helpKey], () => {
  void store?.load()
}, { immediate: true })
</script>

<style scoped>
.context-help {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  flex-shrink: 0;
  padding: 16px;
  margin-bottom: 16px;
  border-radius: 12px;
  background: var(--solaire-blue-light);
  color: var(--q-dark);
}
.context-help__icon { color: var(--solaire-blue-accent); }
.context-help__confirm { background: var(--solaire-blue-accent); color: white; }
.context-help__content { flex: 1; min-width: 0; overflow-wrap: anywhere; }
body.body--dark .context-help { background: var(--solaire-blue-dark); color: inherit; }
</style>
