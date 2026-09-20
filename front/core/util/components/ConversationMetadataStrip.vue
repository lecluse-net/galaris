<template>
  <q-card-section class="conversation-metadata-strip">
    <div
      v-for="item in items"
      :key="item.label"
      class="conversation-metadata-item"
      :class="{
        'conversation-metadata-item--grow': item.grow,
        'conversation-metadata-item--copyable': item.copyValue,
        'conversation-metadata-item--identifier': item.copyValue,
      }"
      :tabindex="item.copyValue ? 0 : undefined"
      :role="item.copyValue ? 'button' : undefined"
      :title="item.copyValue ? t('common.copy') : undefined"
      @click="item.copyValue && copyValue(item.copyValue)"
      @keydown.enter="item.copyValue && copyValue(item.copyValue)"
      @keydown.space.prevent="item.copyValue && copyValue(item.copyValue)"
    >
      <span class="conversation-metadata-label">{{ item.label }}</span>
      <q-badge
        v-if="item.badgeColor"
        :color="item.badgeColor"
        :label="item.value"
      />
      <span v-else class="conversation-metadata-value ellipsis">{{ item.value }}</span>
      <q-icon v-if="item.copyValue" name="content_copy" size="12px" />
    </div>
  </q-card-section>
</template>

<script setup lang="ts">
import { copyToClipboard, useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'

defineProps<{
  items: Array<{
    label: string
    value: string
    badgeColor?: string
    grow?: boolean
    copyValue?: string
  }>
}>()

const $q = useQuasar()
const { t } = useI18n()

async function copyValue(value: string): Promise<void> {
  try {
    await copyToClipboard(value)
    $q.notify({
      message: t('common.copied'),
      color: 'positive',
      icon: 'check_circle',
      timeout: 1500,
      position: 'top',
    })
  } catch {
    $q.notify({
      message: t('common.copyError'),
      color: 'negative',
      icon: 'error',
      timeout: 3000,
      position: 'top',
    })
  }
}
</script>

<style scoped>
.conversation-metadata-strip {
  display: flex;
  align-items: center;
  gap: 6px 20px;
  min-height: 42px;
  padding: 7px 16px;
  overflow: hidden;
}

.conversation-metadata-item {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  min-width: 0;
  white-space: nowrap;
}

.conversation-metadata-item--grow {
  flex: 1 1 220px;
}

.conversation-metadata-item--copyable {
  cursor: pointer;
  border-radius: 4px;
  outline: none;
}

.conversation-metadata-item--copyable:hover,
.conversation-metadata-item--copyable:focus-visible {
  color: var(--q-primary);
  background: rgb(25 118 210 / 8%);
}

.conversation-metadata-item--identifier .conversation-metadata-value {
  max-width: 290px;
  font-family: monospace;
}

.conversation-metadata-label {
  color: #757575;
  font-size: 11px;
  line-height: 1;
}

.conversation-metadata-value {
  min-width: 0;
  font-size: 13px;
  line-height: 1.2;
}

@media (max-width: 599px) {
  .conversation-metadata-strip {
    flex-wrap: wrap;
  }

  .conversation-metadata-item--grow {
    flex-basis: 100%;
  }
}

body.body--dark .conversation-metadata-label {
  color: #bdbdbd;
}

body.body--dark .conversation-metadata-value {
  color: #f5f5f5;
}

body.body--dark .conversation-metadata-item--copyable:hover,
body.body--dark .conversation-metadata-item--copyable:focus-visible {
  background: rgb(144 202 249 / 12%);
}
</style>
