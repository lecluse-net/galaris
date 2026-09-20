<template>
  <q-page class="lab-home q-pa-md">
    <PageHeader help-key="lab" :help-text="$t('contextHelpPages.lab')" :icon="navigationIcon('science')" :title="t('evaluation.home.title')" :description="t('evaluation.home.description')" />

    <div class="lab-home__grid">
      <q-card
        v-for="section in homeSections"
        :key="section.key"
        flat
        class="lab-home__card"
        :style="{
          '--lab-accent': solaire[section.color].accent,
          '--lab-background-light': solaire[section.color].light,
          '--lab-background-dark': solaire[section.color].dark,
        }"
      >
        <q-item clickable :to="labSectionPath(section.slug)" class="lab-home__link">
          <q-item-section avatar top>
            <div class="lab-home__icon">
              <q-icon :name="navigationIcon(section.icon)" size="40px" />
            </div>
          </q-item-section>

          <q-item-section>
            <q-item-label class="text-h6 text-weight-bold">
              {{ t(section.titleKey) }}
            </q-item-label>
            <q-item-label caption class="lab-home__description">
              {{ t(section.descriptionKey) }}
            </q-item-label>
          </q-item-section>
        </q-item>
      </q-card>
    </div>
  </q-page>
</template>

<script setup lang="ts">
import { navigationIcon } from '@/core/navigation'
import { computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { usePrivilegeStore } from '@/core/authorize'
import { PageHeader, solaireCss as solaire } from '@/core/util'
import { labSections, labSectionPath } from '../presentation'
import { allLabPrivileges, hasAnyPrivilege, labSectionPrivileges } from '../access'

const { t } = useI18n()
const router = useRouter()
const privilegeStore = usePrivilegeStore()
const canAccessLab = computed(() => (
  hasAnyPrivilege(privilegeStore.hasPrivilege, allLabPrivileges)
))
const homeSections = computed(() => [
  ...labSections.filter(section => (
    hasAnyPrivilege(privilegeStore.hasPrivilege, labSectionPrivileges[section.key])
  )),
])

watch([() => privilegeStore.loaded, canAccessLab], ([loaded, allowed]) => {
  if (loaded && !allowed) void router.replace('/')
}, { immediate: true })
</script>

<style scoped>
.lab-home {
  min-width: 0;
}

.lab-home__grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 340px), 1fr));
  gap: 20px;
}

.lab-home__card {
  position: relative;
  min-width: 0;
  overflow: hidden;
  border: 1px solid rgb(0 0 0 / 8%);
  border-radius: 12px;
  background: var(--lab-background-light);
  color: #292C30;
  transition: border-color 180ms ease, box-shadow 180ms ease, transform 180ms ease;
}

.lab-home__card::before {
  position: absolute;
  z-index: 1;
  top: 0;
  right: 0;
  left: 0;
  height: 4px;
  content: '';
  background: var(--lab-accent);
}

.lab-home__card:hover,
.lab-home__card:focus-within {
  border-color: color-mix(in srgb, var(--lab-accent) 35%, transparent);
  box-shadow: 0 6px 18px rgb(0 0 0 / 8%);
  transform: translateY(-2px);
}

.lab-home__link {
  min-height: 190px;
  padding: 30px 24px 24px;
  align-items: flex-start;
}

.lab-home__icon {
  display: grid;
  width: 58px;
  height: 58px;
  place-items: center;
  color: #000;
}

.lab-home__description {
  margin-top: 8px;
  color: inherit;
  font-size: 0.92rem;
  line-height: 1.5;
  white-space: normal;
}

body.body--dark .lab-home__card {
  border-color: rgb(255 255 255 / 12%);
  background: var(--lab-background-dark);
  color: #EEEEF0;
}

body.body--dark .lab-home__icon {
  color: #fff;
}

@media (max-width: 599px) {
  .lab-home__grid {
    grid-template-columns: 1fr;
  }

  .lab-home__link {
    min-height: 0;
    padding: 18px;
  }
}
</style>
