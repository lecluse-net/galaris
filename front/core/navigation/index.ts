/**
 * Public API for core/navigation.
 * Exports navigation types, components, and composables.
 */

export { navigationIcon } from './icons'

// Types
export type {
  NavigationNode,
  NavigationNodeWithPath,
  NavigationTree,
  NavigationModule,
  NavigationNodeState,
  MenuConfig,
  MenusConfig,
  MenuType,
  VisibilityFn,
  NavigationBadge,
  BadgeFn
} from './types'

// Store
export { useNavigationStore } from './stores/navigationStore'

// Composables
export { useNavigation } from './composables/useNavigation'
export { usePageTitle } from './composables/usePageTitle'

// Privileges for convenient use in navigation definitions.
export { privileges } from '@/core/authorize'

// Components for automatic imports through a resolver.
// export { default as LeftMenu } from './components/LeftMenu.vue'
// export { default as LeftMenuRecursive } from './components/LeftMenuRecursive.vue'
// export { default as TopMenu } from './components/TopMenu.vue'
// export { default as TabMenu } from './components/TabMenu.vue'
// export { default as NavigationTree } from './components/NavigationTree.vue'
// export { default as SidebarNavigation } from './components/SidebarNavigation.vue'
// export { default as TopNavigation } from './components/TopNavigation.vue'
export { default as LeftMenu } from './components/LeftMenu.vue'
