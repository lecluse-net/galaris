import { defineAsyncView } from './asyncView'

// Shared instances let internal viewers avoid importing their own public barrel.
export const FullscreenPreview = /* @__PURE__ */ defineAsyncView(() => import('./components/FullscreenPreview.vue'))
export const AudioResourcePlayer = /* @__PURE__ */ defineAsyncView(() => import('./components/AudioResourcePlayer.vue'))
export const Model3dThumbnail = /* @__PURE__ */ defineAsyncView(() => import('./components/Model3dThumbnail.vue'))
export const Model3dViewer = /* @__PURE__ */ defineAsyncView(() => import('./components/Model3dViewer.vue'))
export const TextResourcePreview = /* @__PURE__ */ defineAsyncView(() => import('./components/TextResourcePreview.vue'))
