<template>
  <q-page class="public-home">
    <section class="public-hero" aria-labelledby="public-home-title">
      <div class="public-hero__glow public-hero__glow--one" aria-hidden="true" />
      <div class="public-hero__glow public-hero__glow--two" aria-hidden="true" />

      <div class="public-hero__content">
        <div class="public-hero__copy">
          <p class="public-eyebrow public-eyebrow--light">
            <q-icon name="hub" aria-hidden="true" />
            {{ $t('index.public.eyebrow') }}
          </p>
          <h1 id="public-home-title">{{ appLabel }}</h1>
          <h2>{{ $t('index.public.title') }}</h2>
          <p class="public-hero__intro">{{ $t('index.public.intro') }}</p>

          <div class="public-actions">
            <LoginButton
              unelevated
              no-caps
              rounded
              icon="login"
              :label="$t('index.home.login')"
              class="public-actions__primary"
            />
          </div>
        </div>

        <div class="public-hero__visual" aria-hidden="true">
          <div class="public-orbit">
            <span class="public-orbit__node public-orbit__node--top"><q-icon name="forum" /></span>
            <span class="public-orbit__node public-orbit__node--right"><q-icon name="task_alt" /></span>
            <span class="public-orbit__node public-orbit__node--bottom"><q-icon name="memory" /></span>
            <span class="public-orbit__node public-orbit__node--left"><q-icon name="security" /></span>
          </div>
          <div class="public-logo-stage">
            <img src="/logo/256.png" alt="" class="public-logo" />
          </div>
        </div>
      </div>
    </section>

    <main class="public-shell">
      <section class="public-promise" aria-label="Galaris">
        <span class="public-promise__icon" aria-hidden="true"><q-icon name="bolt" /></span>
        <p>{{ $t('index.public.promise') }}</p>
      </section>

      <section class="public-features" aria-labelledby="public-features-title">
        <header class="public-section-header">
          <p class="public-eyebrow">{{ $t('index.public.features.eyebrow') }}</p>
          <h2 id="public-features-title">{{ $t('index.public.features.title') }}</h2>
          <p>{{ $t('index.public.features.intro') }}</p>
        </header>

        <div class="public-feature-grid">
          <article
            v-for="feature in productFeatures"
            :key="feature.key"
            class="public-feature"
            :class="`public-feature--${feature.tone}`"
          >
            <span class="public-feature__icon" aria-hidden="true">
              <q-icon :name="feature.icon" />
            </span>
            <h3>{{ $t(`index.public.features.${feature.key}.title`) }}</h3>
            <p>{{ $t(`index.public.features.${feature.key}.text`) }}</p>
          </article>
        </div>
      </section>
    </main>
  </q-page>
</template>

<script setup lang="ts">
import { settings } from '@/core/settings'
import { LoginButton } from '@/core/user'
import { productFeatures } from '../presentation'

const appLabel = settings.APP_LABEL
</script>

<style scoped>
.public-home {
  --public-text: #273650;
  --public-muted: #66748b;
  --public-line: #e2e8f2;
  --public-surface: #fff;
  overflow: hidden;
  color: var(--public-text);
  background:
    radial-gradient(circle at 4% 65%, color-mix(in srgb, var(--q-secondary) 8%, transparent), transparent 28rem),
    radial-gradient(circle at 96% 90%, color-mix(in srgb, var(--q-primary) 7%, transparent), transparent 30rem),
    #f7f9fc;
}

.public-hero {
  position: relative;
  isolation: isolate;
  overflow: hidden;
  color: #eef5ff;
  background:
    linear-gradient(118deg, rgba(5, 15, 35, 0.97), rgba(11, 38, 62, 0.94)),
    url('/background.jpg') center / cover;
}

.public-hero::after {
  position: absolute;
  z-index: -1;
  right: -8%;
  bottom: -54%;
  width: min(62vw, 760px);
  aspect-ratio: 1;
  border: 1px solid rgba(255, 255, 255, 0.09);
  border-radius: 50%;
  content: '';
}

.public-hero__glow {
  position: absolute;
  z-index: -1;
  width: 420px;
  height: 420px;
  border-radius: 50%;
  filter: blur(90px);
  opacity: 0.3;
  pointer-events: none;
}

.public-hero__glow--one {
  top: -230px;
  left: -90px;
  background: var(--q-primary);
}

.public-hero__glow--two {
  right: 2%;
  bottom: -260px;
  background: var(--q-secondary);
}

.public-hero__content {
  display: grid;
  grid-template-columns: minmax(0, 1.35fr) minmax(300px, 0.65fr);
  gap: clamp(32px, 7vw, 88px);
  align-items: center;
  width: min(1180px, calc(100% - 48px));
  min-height: 660px;
  margin: 0 auto;
  padding: clamp(76px, 9vw, 116px) 0 108px;
}

.public-hero__copy {
  max-width: 720px;
}

.public-eyebrow {
  display: flex;
  gap: 8px;
  align-items: center;
  margin: 0 0 12px;
  color: var(--q-primary);
  font-size: 0.76rem;
  font-weight: 800;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}

.public-eyebrow--light {
  color: #72e1cd;
}

.public-eyebrow .q-icon {
  font-size: 1.15rem;
}

.public-hero h1 {
  margin: 0;
  color: #fff;
  font-size: clamp(3.5rem, 8vw, 6.4rem);
  font-weight: 820;
  line-height: 0.95;
  letter-spacing: -0.065em;
}

.public-hero h2 {
  max-width: 680px;
  margin: 22px 0 0;
  color: #eaf2ff;
  font-size: clamp(1.65rem, 3.5vw, 2.7rem);
  font-weight: 680;
  line-height: 1.15;
  letter-spacing: -0.035em;
}

.public-hero__intro {
  max-width: 670px;
  margin: 22px 0 0;
  color: rgba(226, 237, 252, 0.78);
  font-size: clamp(1rem, 1.7vw, 1.16rem);
  line-height: 1.75;
}

.public-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 30px;
}

.public-actions :deep(.q-btn) {
  min-height: 48px;
  padding: 0 22px;
  font-weight: 720;
  transition: transform 180ms ease, box-shadow 180ms ease, background 180ms ease;
}

.public-actions__primary {
  min-height: 56px !important;
  padding: 0 30px !important;
  color: #06253a !important;
  border: 2px solid rgba(255, 255, 255, 0.72);
  background: linear-gradient(135deg, #6cf4d7, #7bc5ff) !important;
  box-shadow:
    0 0 0 5px rgba(104, 238, 215, 0.12),
    0 16px 42px rgba(57, 213, 190, 0.38);
  font-size: 1.05rem;
  font-weight: 820 !important;
  letter-spacing: 0.01em;
}

.public-actions__primary:hover,
.public-actions__primary:focus-visible {
  background: linear-gradient(135deg, #91ffe9, #a5d9ff) !important;
  box-shadow:
    0 0 0 6px rgba(104, 238, 215, 0.2),
    0 20px 52px rgba(57, 213, 190, 0.5);
  transform: translateY(-2px);
}

.public-hero__visual {
  position: relative;
  display: grid;
  min-height: 390px;
  place-items: center;
}

.public-logo-stage {
  position: relative;
  display: grid;
  width: clamp(210px, 24vw, 290px);
  aspect-ratio: 1;
  place-items: center;
  border: 1px solid rgba(255, 255, 255, 0.14);
  border-radius: 38%;
  background:
    radial-gradient(circle at 35% 28%, rgba(255, 255, 255, 0.18), transparent 30%),
    linear-gradient(145deg, rgba(42, 126, 183, 0.28), rgba(25, 190, 155, 0.16));
  box-shadow: 0 40px 90px rgba(0, 0, 0, 0.38), inset 0 1px 0 rgba(255, 255, 255, 0.16);
  transform: rotate(-4deg);
  backdrop-filter: blur(18px);
}

.public-logo-stage::before {
  position: absolute;
  inset: 12px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 34%;
  content: '';
}

.public-logo {
  width: 68%;
  height: auto;
  filter: drop-shadow(0 18px 24px rgba(0, 0, 0, 0.32));
  transform: rotate(4deg);
}

.public-orbit {
  position: absolute;
  width: min(360px, 30vw);
  aspect-ratio: 1;
  border: 1px dashed rgba(126, 216, 233, 0.28);
  border-radius: 50%;
}

.public-orbit__node {
  position: absolute;
  display: grid;
  width: 46px;
  height: 46px;
  place-items: center;
  color: #cdeafa;
  border: 1px solid rgba(255, 255, 255, 0.16);
  border-radius: 14px;
  background: rgba(10, 31, 55, 0.86);
  box-shadow: 0 10px 28px rgba(0, 0, 0, 0.32);
}

.public-orbit__node .q-icon {
  font-size: 1.35rem;
}

.public-orbit__node--top { top: -23px; left: calc(50% - 23px); }
.public-orbit__node--right { top: calc(50% - 23px); right: -23px; }
.public-orbit__node--bottom { bottom: -23px; left: calc(50% - 23px); }
.public-orbit__node--left { top: calc(50% - 23px); left: -23px; }

.public-shell {
  width: min(1180px, calc(100% - 48px));
  margin: 0 auto;
  padding: 0 0 72px;
}

.public-promise {
  display: flex;
  gap: 18px;
  align-items: center;
  width: min(900px, calc(100% - 32px));
  margin: -36px auto 0;
  padding: 24px 28px;
  border: 1px solid var(--public-line);
  border-radius: 20px;
  background: color-mix(in srgb, var(--public-surface) 92%, transparent);
  box-shadow: 0 22px 58px rgba(25, 43, 73, 0.12);
  backdrop-filter: blur(16px);
}

.public-promise__icon {
  display: grid;
  flex: 0 0 48px;
  width: 48px;
  height: 48px;
  place-items: center;
  color: #fff;
  border-radius: 15px;
  background: linear-gradient(135deg, var(--q-primary), var(--q-secondary));
  box-shadow: 0 10px 24px color-mix(in srgb, var(--q-primary) 28%, transparent);
}

.public-promise__icon .q-icon {
  font-size: 1.55rem;
}

.public-promise p {
  margin: 0;
  color: var(--public-text);
  font-size: clamp(1.03rem, 2vw, 1.3rem);
  font-weight: 720;
  line-height: 1.4;
}

.public-features {
  padding-top: clamp(76px, 10vw, 112px);
}

.public-section-header {
  max-width: 740px;
  margin-bottom: 34px;
}

.public-section-header h2 {
  margin: 0;
  color: var(--public-text);
  font-size: clamp(2rem, 4vw, 3rem);
  font-weight: 790;
  line-height: 1.12;
  letter-spacing: -0.045em;
}

.public-section-header > p:last-child {
  margin: 18px 0 0;
  color: var(--public-muted);
  font-size: 1.04rem;
  line-height: 1.7;
}

.public-feature-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 18px;
}

.public-feature {
  --feature-color: #3971d6;
  --feature-soft: #edf3ff;
  position: relative;
  overflow: hidden;
  min-height: 235px;
  padding: 28px;
  border: 1px solid var(--public-line);
  border-radius: 22px;
  background: var(--public-surface);
  box-shadow: 0 10px 35px rgba(36, 52, 78, 0.055);
  transition: transform 180ms ease, border-color 180ms ease, box-shadow 180ms ease;
}

.public-feature::after {
  position: absolute;
  right: -40px;
  bottom: -65px;
  width: 150px;
  height: 150px;
  border-radius: 50%;
  background: var(--feature-soft);
  content: '';
  opacity: 0.6;
}

.public-feature:hover {
  border-color: color-mix(in srgb, var(--feature-color) 35%, var(--public-line));
  box-shadow: 0 20px 50px rgba(36, 52, 78, 0.11);
  transform: translateY(-3px);
}

.public-feature--teal { --feature-color: #168b7b; --feature-soft: #e4f7f3; }
.public-feature--violet { --feature-color: #8059c9; --feature-soft: #f2ecff; }
.public-feature--amber { --feature-color: #c78112; --feature-soft: #fff4df; }
.public-feature--cyan { --feature-color: #167fa4; --feature-soft: #e7f6fb; }
.public-feature--indigo { --feature-color: #525fc2; --feature-soft: #ebedff; }

.public-feature__icon {
  position: relative;
  z-index: 1;
  display: grid;
  width: 54px;
  height: 54px;
  margin-bottom: 22px;
  place-items: center;
  color: var(--feature-color);
  border-radius: 17px;
  background: var(--feature-soft);
}

.public-feature__icon .q-icon {
  display: grid;
  width: 1em;
  height: 1em;
  place-items: center;
  font-size: 1.65rem;
  line-height: 1;
}

.public-feature h3,
.public-feature p {
  position: relative;
  z-index: 1;
}

.public-feature h3 {
  margin: 0 0 10px;
  color: var(--public-text);
  font-size: 1.16rem;
  font-weight: 760;
  line-height: 1.25;
}

.public-feature p {
  margin: 0;
  color: var(--public-muted);
  line-height: 1.68;
}

body.body--dark .public-home {
  --public-text: #e7edf7;
  --public-muted: #a7b3c6;
  --public-line: #343e4d;
  --public-surface: #1b2028;
  background:
    radial-gradient(circle at 4% 65%, color-mix(in srgb, var(--q-secondary) 14%, transparent), transparent 28rem),
    radial-gradient(circle at 96% 90%, color-mix(in srgb, var(--q-primary) 12%, transparent), transparent 30rem),
    #11151b;
}

body.body--dark .public-promise {
  background: rgba(27, 32, 40, 0.94);
  box-shadow: 0 24px 62px rgba(0, 0, 0, 0.42);
}

body.body--dark .public-feature {
  background: linear-gradient(145deg, #1d232c, #191e25);
  box-shadow: 0 14px 38px rgba(0, 0, 0, 0.28);
}

body.body--dark .public-feature:hover {
  border-color: color-mix(in srgb, var(--feature-color) 44%, var(--public-line));
  box-shadow: 0 24px 56px rgba(0, 0, 0, 0.4);
}

body.body--dark .public-feature--blue { --feature-color: #85aaf2; --feature-soft: #1e2b42; }
body.body--dark .public-feature--teal { --feature-color: #70cfbd; --feature-soft: #18342f; }
body.body--dark .public-feature--violet { --feature-color: #b49ae8; --feature-soft: #2c2540; }
body.body--dark .public-feature--amber { --feature-color: #e5b765; --feature-soft: #372d1c; }
body.body--dark .public-feature--cyan { --feature-color: #71c5df; --feature-soft: #1a303a; }
body.body--dark .public-feature--indigo { --feature-color: #a3acee; --feature-soft: #252b45; }

@media (max-width: 1023px) {
  .public-hero__content {
    grid-template-columns: minmax(0, 1fr) clamp(150px, 24vw, 220px);
    gap: clamp(24px, 4vw, 48px);
    min-height: auto;
    padding: 68px 0 92px;
    text-align: left;
  }

  .public-hero__copy {
    max-width: 680px;
    margin: 0;
  }

  .public-hero__intro {
    margin-right: 0;
    margin-left: 0;
  }

  .public-hero .public-eyebrow,
  .public-actions {
    justify-content: flex-start;
  }

  .public-hero__visual {
    min-height: 260px;
  }

  .public-orbit {
    width: min(220px, 23vw);
  }

  .public-logo-stage {
    width: min(180px, 19vw);
  }
}

@media (max-width: 900px) {
  .public-feature-grid {
    grid-template-columns: 1fr;
  }

  .public-feature {
    min-height: 0;
  }
}

@media (max-width: 700px) {
  .public-hero__content,
  .public-shell {
    width: min(calc(100% - 28px), 1180px);
  }

  .public-hero__content {
    grid-template-columns: minmax(0, 1fr) clamp(88px, 24vw, 116px);
    gap: 14px;
    align-items: start;
    padding: 48px 0 72px;
  }

  .public-hero h1 {
    font-size: clamp(2.6rem, 14vw, 3.8rem);
  }

  .public-hero h2 {
    margin-top: 14px;
    font-size: clamp(1.2rem, 5.5vw, 1.55rem);
  }

  .public-hero__intro {
    margin-top: 14px;
    font-size: 0.92rem;
    line-height: 1.55;
  }

  .public-actions {
    margin-top: 20px;
  }

  .public-actions__primary {
    min-height: 50px !important;
    padding: 0 20px !important;
    font-size: 0.96rem;
  }

  .public-hero__visual {
    align-self: start;
    min-height: 0;
    padding-top: 32px;
  }

  .public-orbit {
    display: none;
  }

  .public-logo-stage {
    width: clamp(82px, 24vw, 112px);
    border-radius: 32%;
  }

  .public-promise {
    align-items: flex-start;
    width: calc(100% - 12px);
    padding: 20px;
  }
}

@media (max-width: 450px) {
  .public-actions :deep(.q-btn) {
    width: 100%;
  }

  .public-promise__icon {
    flex-basis: 42px;
    width: 42px;
    height: 42px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .public-feature {
    transition: none;
  }
}
</style>
