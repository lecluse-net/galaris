<template>
  <template v-for="node in sortedNodes" :key="node.path">
    <!-- Mini mode shows icons only. -->
    <template v-if="mini">
      <q-item
        v-if="node.to || node.href"
        clickable
        :to="node.to"
        :href="node.href"
        :title="translatedDescription(node.description)"
        :active="isNodeActive(node)"
        :class="getItemClass(node)"
        class="mini-item"
        v-ripple
        @click="onNodeClick(node)"
      >
        <q-item-section avatar v-if="node.icon">
          <q-icon :name="navigationIcon(node.icon)" size="24px">
            <q-tooltip>{{ $te(node.label ?? node.key) ? $t(node.label ?? node.key) : node.label }}</q-tooltip>
          </q-icon>
        </q-item-section>
      </q-item>
    </template>

    <!-- Mode Normal : affichage complet -->
    <template v-else>
      <!-- Node with submenu -->
      <template v-if="hasVisibleChildren(node)">
        <div
          class="menu-item-with-children"
          :title="translatedDescription(node.description)"
        >
          <!-- Left side: navigation when a route is defined -->
          <q-item
            v-if="node.to"
            clickable
            :to="node.to"
            :active="isNodeActive(node)"
            :class="getHeaderClass(node)"
            class="menu-item menu-item-main"
            v-ripple
            @click="onNodeClick(node)"
          >
            <q-item-section avatar v-if="node.icon">
              <q-icon :name="navigationIcon(node.icon)" size="24px" />
            </q-item-section>
            <q-item-section>
              <q-item-label>{{ $te(node.label ?? node.key) ? $t(node.label ?? node.key) : node.label }}</q-item-label>
            </q-item-section>
            <q-item-section side v-if="getBadge(node)">
              <q-badge color="secondary">{{ getBadge(node) }}</q-badge>
            </q-item-section>
          </q-item>

          <!-- Left side: label without a route -->
          <q-item
            v-else
            :class="getHeaderClass(node)"
            class="menu-item menu-item-main no-pointer-events"
          >
            <q-item-section avatar v-if="node.icon">
              <q-icon :name="navigationIcon(node.icon)" size="24px" />
            </q-item-section>
            <q-item-section>
              <q-item-label>{{ $te(node.label ?? node.key) ? $t(node.label ?? node.key) : node.label }}</q-item-label>
            </q-item-section>
            <q-item-section side v-if="getBadge(node)">
              <q-badge color="secondary">{{ getBadge(node) }}</q-badge>
            </q-item-section>
          </q-item>

          <!-- Right side: expansion button. -->
          <q-btn
            flat
            dense
            :icon="store.isExpanded(node.path) ? 'expand_less' : 'expand_more'"
            class="expand-btn"
            @click.stop="toggle(node.path)"
          />
        </div>

        <!-- Children displayed while expanded -->
        <div v-show="store.isExpanded(node.path)" class="submenu">
          <q-list class="q-pl-md">
            <LeftMenuItems
              :tree="node.children"
              :parent-path="node.path"
              :depth="depth + 1"
              :mini="mini"
            />
          </q-list>
        </div>
      </template>

      <!-- Leaf link -->
      <q-item
        v-else
        clickable
        :to="node.to"
        :href="node.href"
        :title="translatedDescription(node.description)"
        :active="isNodeActive(node)"
        :class="getItemClass(node)"
        class="menu-item"
        v-ripple
        @click="onNodeClick(node)"
      >
        <q-item-section avatar v-if="node.icon">
          <q-icon :name="navigationIcon(node.icon)" size="24px" />
        </q-item-section>
        <q-item-section>
          <q-item-label>{{ $te(node.label ?? node.key) ? $t(node.label ?? node.key) : node.label }}</q-item-label>
        </q-item-section>
        <q-item-section side v-if="getBadge(node)">
          <q-badge color="secondary">{{ getBadge(node) }}</q-badge>
        </q-item-section>
      </q-item>
    </template>
  </template>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import type { NavigationTree, NavigationNodeWithPath } from '../'
import { useNavigation, useNavigationStore } from '../'
import { navigationIcon } from '../icons'

interface Props {
  tree?: NavigationTree
  parentPath: string
  depth: number
  mini?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  mini: false
})

const route = useRoute()
const store = useNavigationStore()
const { isVisible, getBadgeValue } = useNavigation()
const { t, te } = useI18n()

const sortedNodes = computed<NavigationNodeWithPath[]>(() => {
  if (!props.tree) return []

  const entries = Object.entries(props.tree)
  if (entries.length === 0) return []

  return entries
    .map(([key, node]) => ({
      ...node,
      key,
      path: props.parentPath ? `${props.parentPath}.${key}` : key,
      depth: props.depth,
      childrenKeys: node.children ? Object.keys(node.children) : undefined
    }))
    .filter(node => isVisible(node))
    .sort((a, b) => (a.order ?? 99) - (b.order ?? 99))
})

function toggle(path: string) {
  if (store.isExpanded(path)) {
    store.collapse(path)
  } else {
    store.expand(path)
  }
}

function hasVisibleChildren(node: NavigationNodeWithPath): boolean {
  if (!node.children || Object.keys(node.children).length === 0) return false
  return Object.values(node.children).some(child => isVisible(child))
}

function isNodeActive(node: NavigationNodeWithPath): boolean {
  if (!node.to) return false
  // Use exact matching so startsWith does not mark ancestors as active.
  return route.path === node.to
}

function getBadge(node: NavigationNodeWithPath): string | null {
  return getBadgeValue(node)
}

function translatedDescription(description?: string): string | undefined {
  if (!description) return undefined
  return te(description) ? t(description) : description
}

function getHeaderClass(node: NavigationNodeWithPath): string {
  const classes: string[] = ['menu-item-content']
  // Every active item uses the same styling.
  if (isNodeActive(node)) {
    classes.push('text-primary')
  }
  if (node.class) classes.push(node.class)
  return classes.join(' ')
}

function getItemClass(node: NavigationNodeWithPath): string {
  return node.class || ''
}

function onNodeClick(node: NavigationNodeWithPath) {
  store.setActiveNode(node.path)
}
</script>

<style scoped>
.menu-item-with-children {
  display: flex;
  align-items: stretch;
}

.menu-item-main {
  flex: 1;
  min-width: 0;
}

.menu-item-content {
  border-radius: 0;
}

.menu-item {
  min-height: 32px;
  padding-top: 4px;
  padding-bottom: 4px;
}

.expand-btn {
  border-radius: 0;
  align-self: stretch;
}

.submenu {
  overflow: hidden;
}

:deep(.q-item__section--avatar) {
  min-width: 34px;
  padding-right: 10px;
}

:deep(.q-item__section--avatar > .q-icon) {
  /* Render at 28px while preserving the 24px layout box and row height. */
  transform: scale(1.1666667);
}

.mini-item {
  justify-content: center;
  padding: 8px 0;
}

.mini-item :deep(.q-item__section--avatar) {
  min-width: unset;
  padding-right: 0;
}

.navigation-item--muted {
  opacity: 0.48;
  filter: saturate(0.55);
}
</style>
