<route lang="json">
{ "path": "/graphic-reference", "meta": { "devOnly": true } }
</route>
<template>
  <q-page v-if="settings.is_dev" class="graphic-reference q-pa-md">
    <PageHeader icon="palette" :title="t('graphicReference.title')" :description="t('graphicReference.description')">
      <template #title-after><q-badge outline color="primary">{{ t('graphicReference.dev') }}</q-badge></template>
      <template #actions><div class="row q-gutter-sm">
        <q-btn outline color="primary" :icon="$q.dark.isActive ? 'light_mode' : 'dark_mode'" :label="t($q.dark.isActive ? 'graphicReference.light' : 'graphicReference.dark')" @click="$q.dark.toggle()" />
        <q-btn outline icon="restart_alt" :label="t('graphicReference.reset')" @click="reset" />
      </div></template>
    </PageHeader>
    <p>{{ t('graphicReference.intro') }}</p>
    <nav class="row q-gutter-sm q-mb-lg" :aria-label="t('graphicReference.title')"><q-btn v-for="section in sections" :key="section" outline dense no-caps :label="t(`graphicReference.${section}`)" :href="`#${section}`" /></nav>
    <div :key="generation" class="gallery-grid">
      <GallerySection id="palette" :title="t('graphicReference.palette')" icon="palette" class="wide">
        <div class="palette-grid"><div v-for="color in solaireColors" :key="color" class="palette-color">
          <strong>{{ t(`graphicReference.${color}`) }}</strong>
          <div v-for="variant in ['accent', 'light', 'dark'] as const" :key="variant" class="swatch" :style="{ background: solaireCss[color][variant] }"><code :style="{ color: variant === 'dark' ? '#EEEEF0' : '#292C30' }">{{ solaire[color][variant] }}</code></div>
        </div></div>
      </GallerySection>
      <GallerySection id="actions" :title="t('graphicReference.actions')" icon="touch_app">
        <div class="row q-gutter-sm">
          <q-btn color="primary" icon="add" :label="t('graphicReference.primary')" @click="notify" />
          <q-btn outline color="primary" :label="t('graphicReference.secondary')" @click="notify" />
          <q-btn color="negative" icon="delete" :label="t('graphicReference.delete')" @click="notify" />
          <q-btn disable :label="t('graphicReference.disabled')" />
          <q-btn color="primary" loading :label="t('graphicReference.loading')" />
          <q-btn flat round icon="edit" :aria-label="t('graphicReference.name')"><q-tooltip>{{ t('graphicReference.hint') }}</q-tooltip></q-btn>
          <q-btn flat round color="negative" icon="delete" :aria-label="t('graphicReference.delete')" @click="notify" />
          <q-btn-dropdown outline :label="t('graphicReference.menu')"><q-list><q-item v-close-popup clickable @click="notify"><q-item-section avatar><q-icon name="edit" /></q-item-section><q-item-section>{{ t('graphicReference.sample') }}</q-item-section></q-item></q-list></q-btn-dropdown>
        </div>
        <q-separator spaced />
        <div class="row items-center q-gutter-md"><PersonAvatar :name="t('graphicReference.incoming')" /><DocumentFileIcon size="32px" /><q-chip removable icon="label">{{ t('graphicReference.sample') }}</q-chip><q-badge color="primary">50</q-badge></div>
      </GallerySection>
      <GallerySection id="toggles" :title="t('graphicReference.toggles')" icon="view_week" class="wide"><GalleryToggles /></GallerySection>
      <GallerySection id="dialogs" :title="t('graphicReference.dialogs')" icon="web_asset">
        <div class="mini-modal-stage q-pa-md q-mb-md">
          <GalleryDialogCard v-if="miniModal" @close="miniModal = false" @save="miniModal = false; notify()" />
          <q-btn v-else outline color="primary" :label="t('graphicReference.restore')" @click="miniModal = true" />
        </div>
        <q-btn outline color="primary" :label="t('graphicReference.openModal')" @click="dialog = true" />
        <q-dialog v-model="dialog" :aria-label="t('graphicReference.modalTitle')"><GalleryDialogCard @close="dialog = false" @save="dialog = false; notify()" /></q-dialog>
      </GallerySection>
      <GallerySection id="forms" :title="t('graphicReference.forms')" icon="edit_note" class="wide"><GalleryForms /></GallerySection>
      <GallerySection id="folders" :title="t('graphicReference.folders')" icon="folder" class="wide">
        <div class="scroll"><table class="folder-table"><thead><tr><th>{{ t('graphicReference.name') }}</th><th v-for="size in sizes" :key="size">{{ size }} px</th></tr></thead><tbody>
          <template v-for="tone in tones" :key="tone"><tr v-for="expanded in [false, true]" :key="`${tone}-${expanded}`"><th>{{ t(`graphicReference.${tone}`) }} · {{ t(expanded ? 'graphicReference.opened' : 'graphicReference.closed') }}</th><td v-for="size in sizes" :key="size"><FolderIcon :tone="tone" :expanded="expanded" :size="`${size}px`" /></td></tr></template>
        </tbody></table></div>
      </GallerySection>
      <GallerySection id="navigation" :title="t('graphicReference.navigation')" icon="view_sidebar" class="wide"><GalleryNavigation /></GallerySection>
      <GallerySection id="patterns" :title="t('graphicReference.patterns')" icon="widgets" class="wide"><GalleryPatterns /></GallerySection>
      <GallerySection id="feedback" :title="t('graphicReference.feedback')" icon="notifications">
        <div class="row q-gutter-sm"><StatusBadge v-for="tone in statusTones" :key="tone" :tone="tone" :label="t(`graphicReference.${tone}`)" :icon="statusIcons[tone]" /></div>
        <q-banner v-for="tone in ['blue', 'orange', 'red'] as const" :key="tone" rounded class="q-mt-md" :style="{ background: solaireCss[tone][$q.dark.isActive ? 'dark' : 'light'] }"><template #avatar><q-icon :name="tone === 'blue' ? 'info' : 'warning'" :style="{ color: solaireCss[tone].accent }" /></template>{{ t('graphicReference.notice') }}</q-banner>
        <div class="row items-center q-gutter-md q-my-md"><q-spinner color="primary" size="24px" /><WaitingResponseIndicator :label="t('graphicReference.loading')" /><q-skeleton type="text" width="120px" /><q-circular-progress :value="65" size="40px" color="primary" /></div>
        <q-linear-progress :value="0.65" :aria-label="t('graphicReference.progress')" /><q-linear-progress indeterminate class="q-mt-sm" />
        <q-banner class="q-my-md"><template #avatar><q-icon name="inbox" /></template>{{ t('graphicReference.empty') }}</q-banner>
        <q-btn outline color="primary" :label="t('graphicReference.notify')" @click="notify" />
      </GallerySection>
      <GallerySection :title="t('graphicReference.content')" icon="forum">
        <h3 class="text-h6 q-mt-none">{{ t('graphicReference.typography') }}</h3><p>{{ t('graphicReference.paragraph') }}</p>
        <ConversationBubble :speaker="t('graphicReference.incoming')">{{ t('graphicReference.message') }}</ConversationBubble>
        <ConversationBubble side="outgoing" :speaker="t('graphicReference.outgoing')">{{ t('graphicReference.message') }}</ConversationBubble>
        <ResourcePreviewBlock class="q-mt-md" :title="t('graphicReference.sample')" :description="t('graphicReference.paragraph')" :open-label="t('graphicReference.preview')" @open="notify" />
        <DashboardModelPieChart :slices="slices" :ariaLabel="t('graphicReference.palette')" />
      </GallerySection>
      <GallerySection id="content" :title="t('graphicReference.content')" icon="article" class="wide">
        <q-expansion-item :label="t('graphicReference.fullEditor')" icon="article" default-opened><RichTextEditor v-model="html" profile="document" toolbar-mode="full" :aria-label="t('graphicReference.fullEditor')" /></q-expansion-item>
        <q-expansion-item :label="t('graphicReference.simpleEditor')" icon="edit_note" default-opened><RichTextEditor v-model="simpleHtml" toolbar-mode="simple" :aria-label="t('graphicReference.simpleEditor')" /></q-expansion-item>
        <q-separator spaced /><CodeEditor v-model="code" language="json" :visible-lines="6" :label="t('graphicReference.code')" />
      </GallerySection>
      <GallerySection id="glyphs" :title="t('graphicReference.glyphs')" icon="apps" class="wide"><GalleryInventory /></GallerySection>
    </div>
  </q-page>
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuasar } from 'quasar'
import { settings } from '@/core/settings'
import { PageHeader, FolderIcon, DocumentFileIcon, PersonAvatar, StatusBadge, CodeEditor, RichTextEditor, ResourcePreviewBlock, solaire, solaireCss, solaireColors, type StatusBadgeTone } from '@/core/util'
import { ConversationBubble, WaitingResponseIndicator } from '@/core/util'
import DashboardModelPieChart from '../components/DashboardModelPieChart.vue'
import GallerySection from '../graphic-reference/GallerySection.vue'
import GalleryDialogCard from '../graphic-reference/GalleryDialogCard.vue'
import GalleryForms from '../graphic-reference/GalleryForms.vue'
import GalleryNavigation from '../graphic-reference/GalleryNavigation.vue'
import GalleryInventory from '../graphic-reference/GalleryInventory.vue'
import GalleryPatterns from '../graphic-reference/GalleryPatterns.vue'
import GalleryToggles from '../graphic-reference/GalleryToggles.vue'
const { t } = useI18n(), $q = useQuasar()
const initialDark = $q.dark.mode
onBeforeUnmount(() => $q.dark.set(initialDark))
const generation = ref(0), miniModal = ref(true), dialog = ref(false)
function sampleHtml(): string { return `<h2>${t('graphicReference.typography')}</h2><p><strong>${t('graphicReference.sample')}</strong> · <em>${t('graphicReference.paragraph')}</em></p><blockquote><p>${t('graphicReference.message')}</p></blockquote><ul><li>${t('graphicReference.first')}</li><li>${t('graphicReference.second')}</li></ul><table><tbody><tr><th>${t('graphicReference.name')}</th><th>${t('graphicReference.preview')}</th></tr><tr><td>${t('graphicReference.first')}</td><td>50</td></tr></tbody></table>` }
const html = ref(sampleHtml()), simpleHtml = ref(sampleHtml()), code = ref('{\n  "example": true,\n  "items": [10, 20, 50]\n}')
const sections = ['palette', 'actions', 'toggles', 'dialogs', 'forms', 'folders', 'navigation', 'patterns', 'feedback', 'content', 'glyphs']
const sizes = [16, 20, 22, 24, 26, 32, 48, 64, 88]
const tones = ['default', ...solaireColors] as const
const statusTones: StatusBadgeTone[] = ['active', 'success', 'warning', 'error', 'neutral']
const statusIcons = { active: 'play_arrow', success: 'check', warning: 'warning', error: 'error', neutral: 'schedule' }
const slices = computed(() => ['blue', 'orange', 'green'].map((key, index) => ({ key, label: t(`graphicReference.${key}`), color: solaireCss[key as 'blue' | 'orange' | 'green'].accent, share: [0.5, 0.3, 0.2][index]! })))
function notify(): void { $q.notify({ message: t('graphicReference.notice'), type: 'positive' }) }
function reset(): void { generation.value++; miniModal.value = true; dialog.value = false; html.value = sampleHtml(); simpleHtml.value = sampleHtml(); code.value = '{\n  "example": true,\n  "items": [10, 20, 50]\n}' }
</script>
<style scoped>
.graphic-reference { padding-top: 60px; max-width: 1800px; margin: 0 auto; }
.gallery-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 20px; }
.wide { grid-column: 1 / -1; }
.palette-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(100px, 1fr)); gap: 12px; }
.palette-color strong { display: block; min-height: 40px; font-size: 12px; }
.swatch { padding: 10px 4px; text-align: center; }
.swatch code { font-size: 11px; }
.mini-modal-stage { display: grid; place-items: center; min-height: 260px; background: color-mix(in srgb, currentColor 8%, transparent); border-radius: 8px; }
.folder-table { width: 100%; border-collapse: collapse; }
.folder-table th, .folder-table td { padding: 8px; text-align: center; border-bottom: 1px solid color-mix(in srgb, currentColor 12%, transparent); }
.folder-table tbody th { text-align: left; font-weight: normal; white-space: nowrap; }
:deep(.pie-chart) { max-width: 180px; margin: 16px auto 0; }
@media (max-width: 1023px) { .gallery-grid { grid-template-columns: minmax(0, 1fr); } }
</style>
