<template>
  <div class="preferences-menu-grid">
    <q-card
      v-for="item in items"
      :key="item.key"
      flat
      class="preferences-menu-grid__card"
      :class="{
        'preferences-menu-grid__card--inactive': item.inactive,
        'preferences-menu-grid__card--colored': item.color,
      }"
      :style="item.color ? {
        '--preferences-accent': solaire[item.color].accent,
        '--preferences-background-light': solaire[item.color].light,
        '--preferences-background-dark': solaire[item.color].dark,
      } : {
        '--preferences-accent': item.accent ?? '#0284c7',
        '--preferences-accent-secondary': item.accentSecondary ?? '#6366f1',
      }"
    >
      <q-item clickable :to="item.to" class="preferences-menu-grid__link">
        <q-item-section avatar top>
          <div class="preferences-menu-grid__icon">
            <img
              v-if="item.image"
              :src="item.image"
              alt=""
              class="preferences-menu-grid__image"
            >
            <q-icon v-else :name="navigationIcon(item.icon)" size="40px" />
          </div>
        </q-item-section>

        <q-item-section>
          <q-item-label class="row items-center q-gutter-sm text-h6 text-weight-bold">
            <span>{{ item.title }}</span>
            <q-badge v-if="item.badge" rounded color="primary" :label="item.badge" />
          </q-item-label>
          <q-item-label caption class="preferences-menu-grid__description">
            {{ item.description }}
          </q-item-label>
        </q-item-section>
      </q-item>
    </q-card>
  </div>
</template>

<script setup lang="ts">
import { navigationIcon } from '@/core/navigation'
import { solaireCss as solaire, type SolaireColor } from '@/core/util'

interface PreferencesMenuItem {
  key: string
  title: string
  description: string
  icon: string
  image?: string
  to: string
  color?: SolaireColor
  accent?: string
  accentSecondary?: string
  badge?: string
  inactive?: boolean
}

defineProps<{ items: PreferencesMenuItem[] }>()
</script>

<style scoped>
.preferences-menu-grid {
  display: grid;
  min-width: 0;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 340px), 1fr));
  gap: 20px;
}

.preferences-menu-grid__card {
  --preferences-accent: var(--q-primary);
  --preferences-accent-secondary: var(--q-secondary);
  position: relative;
  min-width: 0;
  overflow: hidden;
  border: 1px solid color-mix(in srgb, var(--preferences-accent) 30%, rgba(0, 0, 0, 0.12));
  background:
    radial-gradient(circle at 100% 0%, color-mix(in srgb, var(--preferences-accent-secondary) 18%, transparent) 0, transparent 42%),
    linear-gradient(145deg, color-mix(in srgb, var(--preferences-accent) 9%, white), white 62%);
  transition: border-color 180ms ease, box-shadow 180ms ease, transform 180ms ease;
}

.preferences-menu-grid__card::before {
  position: absolute;
  z-index: 1;
  top: 0;
  right: 0;
  left: 0;
  height: 5px;
  content: '';
  background: linear-gradient(90deg, var(--preferences-accent), var(--preferences-accent-secondary));
}

.preferences-menu-grid__card:hover,
.preferences-menu-grid__card:focus-within {
  border-color: color-mix(in srgb, var(--preferences-accent) 70%, transparent);
  box-shadow: 0 14px 32px color-mix(in srgb, var(--preferences-accent) 22%, transparent);
  transform: translateY(-4px);
}

.preferences-menu-grid__card--inactive {
  opacity: 0.46;
  filter: saturate(0.55);
}

.preferences-menu-grid__card--inactive:hover,
.preferences-menu-grid__card--inactive:focus-within {
  opacity: 0.72;
}

.preferences-menu-grid__link {
  min-height: 190px;
  padding: 30px 24px 24px;
  align-items: flex-start;
}

.preferences-menu-grid__icon {
  display: grid;
  width: 58px;
  height: 58px;
  overflow: hidden;
  place-items: center;
  border: 1px solid color-mix(in srgb, var(--preferences-accent) 18%, transparent);
  border-radius: 18px;
  color: var(--preferences-accent);
  background: color-mix(in srgb, var(--preferences-accent) 8%, transparent);
}

.preferences-menu-grid__image {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.preferences-menu-grid__description {
  margin-top: 8px;
  color: inherit;
  font-size: 0.92rem;
  line-height: 1.5;
  white-space: normal;
}

body.body--dark .preferences-menu-grid__card {
  border-color: color-mix(in srgb, var(--preferences-accent) 44%, rgba(255, 255, 255, 0.2));
  background:
    radial-gradient(circle at 100% 0%, color-mix(in srgb, var(--preferences-accent-secondary) 22%, transparent) 0, transparent 44%),
    linear-gradient(145deg, color-mix(in srgb, var(--preferences-accent) 14%, #1d1d1d), #1d1d1d 64%);
}

.preferences-menu-grid__card--colored {
  border-color: rgb(0 0 0 / 8%);
  border-radius: 12px;
  background: var(--preferences-background-light);
  color: #292C30;
}

.preferences-menu-grid__card--colored::before {
  height: 4px;
  background: var(--preferences-accent);
}

.preferences-menu-grid__card--colored .preferences-menu-grid__icon {
  border: 0;
  border-radius: 0;
  background: transparent;
  color: #000;
}

.preferences-menu-grid__card--colored:hover,
.preferences-menu-grid__card--colored:focus-within {
  border-color: color-mix(in srgb, var(--preferences-accent) 35%, transparent);
  box-shadow: 0 6px 18px rgb(0 0 0 / 8%);
  transform: translateY(-2px);
}

body.body--dark .preferences-menu-grid__card--colored {
  border-color: rgb(255 255 255 / 12%);
  background: var(--preferences-background-dark);
  color: #EEEEF0;
}

body.body--dark .preferences-menu-grid__card--colored .preferences-menu-grid__icon {
  color: #fff;
}

@media (max-width: 599px) {
  .preferences-menu-grid {
    grid-template-columns: 1fr;
  }

  .preferences-menu-grid__link {
    min-height: 0;
    padding: 18px;
  }
}
</style>
