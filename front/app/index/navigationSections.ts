interface NavigationSection {
  rootKey: string
  label?: string
}

export const navigationSections: readonly NavigationSection[] = [
  { rootKey: 'configure', label: 'index.sidebar.configure' },
  { rootKey: 'act', label: 'index.sidebar.act' },
  { rootKey: 'knowledge', label: 'index.sidebar.knowledge' },
  { rootKey: 'monitor', label: 'index.sidebar.monitor' },
  { rootKey: 'admin', label: 'index.sidebar.administration' },
] as const
