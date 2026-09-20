<template>
  <q-card-section
    class="section-header"
    :class="{
      'section-header--compact': compact,
      'section-header--inline-mobile': inlineOnMobile,
    }"
  >
    <div class="section-header__identity">
      <div class="section-header__icon" :class="`section-header__icon--${tone}`">
        <q-icon :name="icon" size="23px" />
      </div>
      <div class="section-header__copy">
        <div class="section-header__title-row">
          <h2>{{ title }}</h2>
          <slot name="badge"></slot>
        </div>
        <p>{{ subtitle }}</p>
      </div>
    </div>
    <div v-if="$slots.action" class="section-header__action">
      <slot name="action"></slot>
    </div>
  </q-card-section>
</template>

<script setup lang="ts">
defineProps<{
  icon: string
  title: string
  subtitle: string
  tone?: 'blue' | 'violet' | 'teal' | 'amber'
  compact?: boolean
  inlineOnMobile?: boolean
}>()
</script>

<style scoped>
.section-header {
  display: flex;
  min-height: 88px;
  gap: 20px;
  align-items: center;
  justify-content: space-between;
  padding: 18px 22px;
}

.section-header__identity { display: flex; min-width: 0; gap: 13px; align-items: center; }
.section-header__icon { display: grid; flex: 0 0 45px; width: 45px; height: 45px; color: var(--section-color); border-radius: 13px; background: var(--section-soft); place-items: center; }
.section-header__icon--blue { --section-color: #426fe5; --section-soft: #edf2ff; }
.section-header__icon--violet { --section-color: #8156df; --section-soft: #f2edff; }
.section-header__icon--teal { --section-color: #078d78; --section-soft: #e7f7f3; }
.section-header__icon--amber { --section-color: #dc881a; --section-soft: #fff4e2; }

body.body--dark .section-header__icon--blue { --section-color: #9ab2f0; --section-soft: #1e2740; }
body.body--dark .section-header__icon--violet { --section-color: #b39ae8; --section-soft: #2b2340; }
body.body--dark .section-header__icon--teal { --section-color: #6fcab8; --section-soft: #17302b; }
body.body--dark .section-header__icon--amber { --section-color: #e8b168; --section-soft: #362b15; }
.section-header__copy { min-width: 0; }
.section-header__title-row { display: flex; gap: 9px; align-items: center; flex-wrap: wrap; }
.section-header h2 { margin: 0; color: #1e2b47; font-size: 1.08rem; font-weight: 780; line-height: 1.25; }
body.body--dark .section-header h2 { color: #dbe2ee; }
.section-header p { margin: 4px 0 0; color: #8b95a8; font-size: 0.78rem; line-height: 1.4; }
.section-header__action { display: flex; flex: 0 0 auto; gap: 8px; align-items: center; }
.section-header--compact { min-height: 64px; gap: 12px; padding-block: 9px; }

@media (max-width: 599px) {
  .section-header { align-items: flex-start; flex-direction: column; }
  .section-header__action { width: 100%; }
  .section-header__action :deep(.q-btn-group),
  .section-header__action :deep(.q-btn-toggle) { width: 100%; }
  .section-header--inline-mobile { align-items: center; flex-direction: row; }
  .section-header--inline-mobile .section-header__action { width: auto; }
}
</style>
