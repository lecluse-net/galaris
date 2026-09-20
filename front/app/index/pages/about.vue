<template>
  <q-page class="about-page">
    <header class="about-hero">
      <div class="about-brand">
        <img src="/logo/256.png" :alt="t('index.about.logoAlt')" width="112" height="112" class="about-logo" />
        <div>
          <p class="about-eyebrow">{{ t('nav.about') }}</p>
          <h1>{{ settings.APP_LABEL }}</h1>
          <p class="about-tagline">{{ t('index.about.tagline') }}</p>
        </div>
      </div>
      <p class="about-intro">{{ t('index.about.description') }}</p>
      <div class="about-version">
        <q-icon name="new_releases" size="28px" aria-hidden="true" />
        <div>
          <span class="about-version__label">{{ t('index.about.currentVersion') }}</span>
          <strong class="about-version__value">{{ version }}</strong>
        </div>
      </div>
    </header>

    <section class="about-features" aria-labelledby="about-features-title">
      <h2 id="about-features-title">{{ t('index.about.featuresTitle') }}</h2>
      <p class="about-section-intro">{{ t('index.about.featuresIntro') }}</p>
      <ul class="about-feature-grid">
        <li
          v-for="feature in features"
          :key="feature.key"
          class="about-feature"
          :style="{
            '--feature-accent': solaireCss[feature.color].accent,
            '--feature-light': solaireCss[feature.color].light,
            '--feature-dark': solaireCss[feature.color].dark,
          }"
        >
          <span class="about-feature__icon" aria-hidden="true">
            <q-icon :name="feature.icon" size="26px" />
          </span>
          <div>
            <h3>{{ t(`index.about.features.${feature.key}.title`) }}</h3>
            <p>{{ t(`index.about.features.${feature.key}.text`) }}</p>
          </div>
        </li>
      </ul>
    </section>

    <footer class="about-footer">
      <div>
        <p class="about-footer__title">{{ t('index.about.openSource') }}</p>
        <a href="https://lecluse.net" target="_blank" rel="noopener noreferrer" class="author-link">
          {{ t('index.about.copyright') }}
        </a>
      </div>
      <div class="about-footer__actions">
        <q-btn flat no-caps color="primary" to="/license" icon="description" :label="t('nav.license')" />
        <q-btn flat no-caps color="primary" to="/" icon="arrow_back" :label="t('index.backHome')" />
      </div>
    </footer>
  </q-page>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { settings } from '@/core/settings'
import { solaireCss } from '@/core/util'

const { t } = useI18n()
const version = computed(() => settings.APP_VERSION || t('index.about.unknownVersion'))
const features = [
  { key: 'agents', icon: 'groups', color: 'blue' },
  { key: 'tasks', icon: 'track_changes', color: 'violet' },
  { key: 'conversations', icon: 'forum', color: 'green' },
  { key: 'tools', icon: 'construction', color: 'orange' },
  { key: 'documents', icon: 'description', color: 'cyan' },
  { key: 'memory', icon: 'psychology', color: 'iris' },
  { key: 'models', icon: 'hub', color: 'fuchsia' },
  { key: 'control', icon: 'shield', color: 'salmon' },
] as const
</script>

<style scoped>
.about-page {
  max-width: 1080px;
  margin: 0 auto;
  padding: 40px 32px;
  overflow-wrap: anywhere;
}

.about-hero {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(220px, 280px);
  gap: 24px 40px;
  padding-bottom: 36px;
  border-bottom: 1px solid var(--solaire-gray-light);
}

.about-brand {
  display: flex;
  align-items: center;
  gap: 24px;
}

.about-logo {
  flex: 0 0 auto;
  object-fit: contain;
}

.about-eyebrow {
  margin: 0 0 6px;
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.about-brand h1 {
  margin: 0;
  font-size: clamp(36px, 5vw, 48px);
  font-weight: 700;
  line-height: 1.15;
  letter-spacing: -0.03em;
}

.about-tagline {
  margin: 10px 0 0;
  font-size: 16px;
  line-height: 1.5;
}

.about-intro {
  grid-column: 1;
  margin: 0;
  font-size: 16px;
  line-height: 1.75;
}

.about-version {
  grid-column: 2;
  grid-row: 1 / 3;
  align-self: center;
  display: flex;
  align-items: flex-start;
  gap: 14px;
  padding: 24px;
  border-radius: 20px;
  background: var(--solaire-blue-light);
}

.about-version > .q-icon {
  color: var(--solaire-blue-accent);
}

.about-version__label {
  display: block;
  margin-bottom: 8px;
  font-size: 13px;
  font-weight: 500;
}

.about-version__value {
  display: block;
  font-size: 28px;
  line-height: 1.25;
}

.about-features {
  padding: 32px 0;
}

.about-features h2 {
  margin: 0 0 8px;
  font-size: 24px;
  font-weight: 600;
  line-height: 1.4;
}

.about-section-intro {
  margin: 0 0 28px;
  line-height: 1.6;
}

.about-feature-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 28px 36px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.about-feature {
  display: flex;
  align-items: flex-start;
  gap: 16px;
}

.about-feature__icon {
  display: grid;
  place-items: center;
  flex: 0 0 52px;
  height: 52px;
  border-radius: 16px;
  color: var(--feature-accent);
  background: var(--feature-light);
}

.about-feature h3 {
  margin: 2px 0 6px;
  font-size: 16px;
  font-weight: 600;
  line-height: 1.4;
}

.about-feature p {
  margin: 0;
  line-height: 1.65;
}

.about-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 20px;
  padding-top: 24px;
  border-top: 1px solid var(--solaire-gray-light);
}

.about-footer__title {
  margin: 0 0 6px;
  font-weight: 500;
}

.about-footer__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.author-link {
  color: inherit;
  text-underline-offset: 3px;
}

body.body--dark .about-version {
  background: var(--solaire-blue-dark);
}

body.body--dark .about-feature__icon {
  background: var(--feature-dark);
}

body.body--dark .about-hero,
body.body--dark .about-footer {
  border-color: var(--solaire-gray-dark);
}

@media (max-width: 1023px) {
  .about-page {
    padding: 24px 20px;
  }

  .about-hero,
  .about-feature-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .about-brand {
    gap: 16px;
  }

  .about-logo {
    width: 80px;
    height: 80px;
  }

  .about-version {
    grid-column: 1;
    grid-row: auto;
  }
}
</style>
