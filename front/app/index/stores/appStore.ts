/**
 * Pinia store for application-wide state.
 * Manages the sidebar's open and compact states.
 */

import { ref } from 'vue'
import { defineStore } from 'pinia'

export const useAppStore = defineStore('app', () => {
  // ============ State ============

  /** Whether the sidebar drawer is open. */
  const sidebarOpen = ref(true)

  /** Compact sidebar mode showing icons only. */
  const sidebarMini = ref(false)

  // ============ Actions ============

  /**
   * Open or close the sidebar.
   */
  function toggleSidebar() {
    sidebarOpen.value = !sidebarOpen.value
  }

  /**
   * Toggle compact sidebar mode.
   */
  function toggleSidebarMini() {
    sidebarMini.value = !sidebarMini.value
  }

  /**
   * Set compact mode explicitly.
   */
  function setSidebarMini(value: boolean) {
    sidebarMini.value = value
  }

  // ============ Exports ============

  return {
    // State.
    sidebarOpen,
    sidebarMini,

    // Actions
    toggleSidebar,
    toggleSidebarMini,
    setSidebarMini
  }
})
