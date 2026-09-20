<template>
  <section class="html-preview" @click.stop>
    <div class="html-toolbar">
      <span class="html-label">
        <q-icon name="html" size="16px" />
        {{ t('htmlPreview.title') }}
        <span class="safe-label">
          <q-icon name="lock" size="12px" />
          {{ t('htmlPreview.isolated') }}
        </span>
      </span>
      <q-btn
        flat
        dense
        no-caps
        size="sm"
        icon="content_copy"
        :label="t('common.copyShort')"
        :aria-label="t('common.copy')"
        class="copy-action"
        @click.stop="copySource"
      >
        <q-tooltip>{{ t('common.copy') }}</q-tooltip>
      </q-btn>
    </div>
    <iframe
      class="html-frame"
      sandbox=""
      referrerpolicy="no-referrer"
      loading="lazy"
      :title="t('htmlPreview.frameTitle')"
      :srcdoc="previewDocument"
    />
    <div v-if="containsForm" class="form-notice">
      <q-icon name="shield" size="14px" />
      {{ t('htmlPreview.formNotice') }}
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { copyToClipboard, useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import { sanitizePreviewHtml } from '../sanitizeHtml'

const props = defineProps<{ content: string }>()
const $q = useQuasar()
const { t } = useI18n()

const containsForm = computed(() => /<(?:form|input|select|textarea|button)\b/i.test(props.content))
const previewDocument = computed(() => {
  const foreground = $q.dark.isActive ? '#e6e9ef' : '#20242c'
  const background = $q.dark.isActive ? '#202329' : '#ffffff'
  const surface = $q.dark.isActive ? '#2b3037' : '#f5f7fa'
  const border = $q.dark.isActive ? '#4a515c' : '#d8dde6'
  const content = sanitizePreviewHtml(props.content)
  return `<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src https: data:; style-src 'unsafe-inline'; form-action 'none'; base-uri 'none'"><meta name="viewport" content="width=device-width,initial-scale=1"><style>html{color-scheme:${$q.dark.isActive ? 'dark' : 'light'}}*{box-sizing:border-box}body{margin:0;padding:14px;color:${foreground};background:${background};font:14px/1.5 system-ui,-apple-system,sans-serif;overflow-wrap:anywhere}img{display:block;max-width:100%;height:auto;margin:8px auto;border-radius:6px}table{width:100%;border-collapse:collapse}th,td{padding:6px 8px;border:1px solid ${border};text-align:left}pre,code{font-family:ui-monospace,monospace}pre{padding:9px;overflow:auto;background:${surface};border-radius:6px}blockquote{margin:8px 0;padding-left:10px;border-left:3px solid ${border}}form{display:grid;gap:10px;padding:10px;background:${surface};border:1px solid ${border};border-radius:7px}label{display:grid;gap:4px;font-weight:600}input,select,textarea,button{max-width:100%;padding:7px 9px;color:${foreground};background:${background};border:1px solid ${border};border-radius:5px;font:inherit}button{width:max-content;cursor:default}a{color:#3f8fe5}</style></head><body>${content}</body></html>`
})

async function copySource(): Promise<void> {
  try {
    await copyToClipboard(props.content)
    $q.notify({ type: 'positive', message: t('common.copied'), timeout: 2_000, position: 'top-right' })
  } catch {
    $q.notify({ type: 'negative', message: t('common.copyError'), timeout: 2_000, position: 'top-right' })
  }
}
</script>

<style scoped>
.html-preview { margin: 8px 0; overflow: hidden; background: #fff; border: 1px solid rgba(53, 69, 94, .16); border-radius: 8px; }
.html-toolbar { display: flex; min-height: 32px; align-items: center; justify-content: space-between; gap: 8px; padding: 2px 5px 2px 9px; color: #657184; background: #f0f3f7; border-bottom: 1px solid rgba(53, 69, 94, .1); }
.html-label, .safe-label { display: inline-flex; align-items: center; gap: 5px; }
.html-label { font-size: .68rem; font-weight: 650; letter-spacing: .035em; text-transform: uppercase; }
.safe-label { color: #8490a0; font-size: .59rem; font-weight: 500; letter-spacing: 0; text-transform: none; }
.copy-action { min-height: 25px; color: #657184; font-size: .68rem; }
.html-frame { display: block; width: 100%; height: min(360px, 55vh); border: 0; background: #fff; }
.form-notice { display: flex; align-items: center; gap: 5px; padding: 5px 9px; color: #7a8493; background: #f7f8fa; border-top: 1px solid rgba(53, 69, 94, .09); font-size: .62rem; }
:global(body.body--dark) .html-preview { background: #202329; border-color: rgba(255, 255, 255, .12); }
:global(body.body--dark) .html-toolbar { color: #abb6c6; background: #2d323a; border-bottom-color: rgba(255, 255, 255, .09); }
:global(body.body--dark) .safe-label, :global(body.body--dark) .copy-action { color: #9ca8b8; }
:global(body.body--dark) .html-frame { background: #202329; }
:global(body.body--dark) .form-notice { color: #9ca8b8; background: #292d33; border-top-color: rgba(255, 255, 255, .08); }
</style>
