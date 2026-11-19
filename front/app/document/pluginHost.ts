import {
  computed, createBlock, createCommentVNode, createElementBlock, createElementVNode, createTextVNode, createVNode,
  defineComponent, Fragment, h, markRaw, nextTick, normalizeClass, normalizeStyle, onBeforeUnmount, onMounted,
  onUnmounted, openBlock, reactive, ref, renderList, renderSlot, resolveComponent, shallowRef, toDisplayString,
  unref, useTemplateRef, vModelText, vShow, watch, watchEffect, withCtx, withDirectives, withKeys, withModifiers,
} from 'vue'
import { useI18n } from 'vue-i18n'
import { QBanner, QBtn, QBtnToggle, QSpace, QSpinner } from 'quasar'
import { DocumentCard, DocumentEmbed, DocumentLink, DocumentToolbar, saveBlobAsResource, solaire } from '@/core/util/facade'

export const pluginHost = Object.freeze({
  vue: Object.freeze({
    computed, createBlock, createCommentVNode, createElementBlock, createElementVNode, createTextVNode, createVNode,
    defineComponent, Fragment, h, markRaw, nextTick, normalizeClass, normalizeStyle, onBeforeUnmount, onMounted,
    onUnmounted, openBlock, reactive, ref, renderList, renderSlot, resolveComponent, shallowRef, toDisplayString,
    unref, useTemplateRef, vModelText, vShow, watch, watchEffect, withCtx, withDirectives, withKeys, withModifiers,
  }),
  useI18n,
  DocumentToolbar,
  DocumentLink,
  DocumentCard,
  DocumentEmbed,
  saveBlobAsResource,
  solaire,
  quasar: Object.freeze({ QBanner, QBtn, QBtnToggle, QSpace, QSpinner }),
})
