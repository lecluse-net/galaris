<template>
  <header class="page-header">
    <div class="page-header__identity">
      <q-icon :name="icon" class="page-header__icon" aria-hidden="true" />
      <div class="page-header__copy">
        <div class="page-header__title-line">
          <h1 class="page-header__title">{{ title }}</h1>
          <div v-if="$slots['title-after']" class="page-header__title-after">
            <slot name="title-after" />
          </div>
        </div>
        <div v-if="description" class="page-header__description text-subtitle1 text-grey-7">
          {{ description }}
        </div>
      </div>
    </div>

    <div v-if="$slots.actions" class="page-header__actions">
      <slot name="actions" />
    </div>
  </header>

  <q-separator class="page-header__separator" />
  <ContextHelp v-if="helpKey && helpText" :help-key="helpKey" :text="helpText" />
</template>

<script setup lang="ts">
import ContextHelp from './ContextHelp.vue'

defineProps<{
  icon: string
  title: string
  description?: string
  helpKey?: string
  helpText?: string
}>()
</script>

<style scoped>
.page-header:first-child {
  margin-top: -10px;
}

.page-header {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px 16px;
}

.page-header__identity {
  display: flex;
  align-items: center;
  gap: 14px;
  flex: 1 1 320px;
  min-width: 0;
}

.page-header__copy {
  flex: 1;
  min-width: 0;
}

.page-header__title-line {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
}

.page-header__title {
  min-width: 0;
  margin: 0;
  overflow-wrap: anywhere;
}

.page-header__icon {
  flex: 0 0 auto;
  font-size: 64px;
}

.page-header__title-after {
  flex: 0 0 auto;
}

.page-header__description {
  margin-top: 4px;
  line-height: 1.4;
}

.page-header__actions {
  flex: 0 0 auto;
}

.page-header__separator {
  margin: 10px 0 14px;
}

@media (max-width: 1023.98px) {
  .page-header__identity {
    gap: 10px;
  }

  .page-header__icon {
    font-size: 32px;
  }

  .page-header__title {
    font-size: 1.5rem;
  }
}

@media (max-width: 600px) {
  .page-header__actions {
    width: 100%;
  }
}
</style>
