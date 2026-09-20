/**
 * Types and interfaces for tree navigation.
 *
 * Trees use keyed objects rather than arrays; keys act as stable IDs.
 * Exemple:
 * {
 *   administration: {
 *     label: 'Administration',
 *     children: {
 *       settings: {
 *         label: 'Settings',
 *         icon: 'people',
 *         order: 20,
 *         to: '/params',
 *         children: { ... }
 *       }
 *     }
 *   }
 * }
 */

/** Visibility predicate. */
export type VisibilityFn = () => boolean

/** Fonction de badge dynamique */
export type BadgeFn = () => string

/** Navigation tree node. */
export interface NavigationNode {
  /** Required displayed label. */
  label?: string

  /** Material icon. */
  icon?: string

  /** Internal route rendered with router-link. */
  to?: string

  /** External link rendered with an anchor. */
  href?: string

  /** Display order; lower values appear first. Defaults to 99. */
  order?: number

  /** Child menu nodes. */
  children?: NavigationTree

  /** Condition d'affichage */
  visible?: boolean | VisibilityFn

  /** Expansion state for folders. */
  expanded?: boolean

  /** Static badge text or a dynamic badge function. */
  badge?: string | BadgeFn

  /** Tooltip or subtitle description. */
  description?: string

  /** Classe CSS additionnelle */
  class?: string

  /** Privileges required to view this item. */
  privileges?: string[]
}

/** Navigation tree keyed by stable IDs. */
export interface NavigationTree {
  [key: string]: NavigationNode
}

/** Navigation definition exported by a module. */
export interface NavigationModule {
  default?: NavigationTree
}

/** Node state stored by the navigation store. */
export interface NavigationNodeState {
  expanded: boolean
  active: boolean
  visible: boolean
}

/** Configuration for a menu type such as sidebar, top bar, or tabs. */
export interface MenuConfig {
  /** Root key of the displayed tree, for example 'administration'. */
  rootKey: string

  /** Displayed menu label. */
  label: string

  /** Material icon. */
  icon?: string

  /** Display order. */
  order?: number

  /** Maximum displayed depth; undefined means unlimited. */
  maxDepth?: number
}

/** Supported menu types. */
export type MenuType = 'left' | 'top' | 'tabs'

/** Complete menu configuration. */
export interface MenusConfig {
  left?: MenuConfig    // Left sidebar menu.
  top?: MenuConfig     // Top menu.
  tabs?: MenuConfig    // Tab menu.
}

/** Node with its tree path for rendering. */
export interface NavigationNodeWithPath extends NavigationNode {
  /** Node key. */
  key: string

  /** Complete path with dot-separated ancestor keys. */
  path: string

  /** Tree depth; zero is the root. */
  depth: number

  /** Child keys. */
  childrenKeys?: string[]
}
