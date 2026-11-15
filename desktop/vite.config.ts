import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { quasar, transformAssetUrls } from '@quasar/vite-plugin'

export default defineConfig({
  root: 'renderer',
  base: './',
  plugins: [vue({ template: { transformAssetUrls } }), quasar()],
  define: { __VUE_I18N_LEGACY_API__: false, __VUE_I18N_FULL_INSTALL__: true },
  build: { outDir: '../dist', emptyOutDir: true }
})
