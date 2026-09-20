import './icons.css'

/** Shared UI artwork for navigation, page headings and section cards. */
const navigationIcons = new Map<string, string>([
  ['smart_toy', 'smart_toy'],
  ['people', 'people'],
  ['groups', 'groups'],
  ['build', 'build'],
  ['psychology', 'psychology'],
  ['forum', 'forum'],
  ['flag_circle', 'flag_circle'],
  ['account_tree', 'account_tree'],
  ['description', 'description'],
  ['memory', 'memory'],
  ['contacts', 'contacts'],
  ['folder_copy', 'folder_copy'],
  ['dashboard', 'dashboard'],
  ['monitor_heart', 'monitor_heart'],
  ['bedtime', 'bedtime'],
  ['outbox', 'outbox'],
  ['settings', 'settings'],
  ['science', 'science'],
  ['terminal', 'terminal'],
  ['security', 'security'],
  ['language', 'language'],
  ['call', 'call'],
  ['graphic_eq', 'graphic_eq'],
  ['task_alt', 'task_alt'],
  ['search', 'search'],
  ['hub', 'hub'],
  ['receipt_long', 'receipt_long'],
  ['manage_search', 'manage_search'],
  ['alt_route', 'alt_route'],
  ['assignment', 'assignment'],
  ['topic', 'topic'],
  ['psychology_alt', 'psychology_alt'],
  ['model_training', 'model_training'],
  ['track_changes', 'track_changes'],
  ['record_voice_over', 'record_voice_over'],
  ['settings_voice', 'record_voice_over'],
  ['bug_report', 'bug_report'],
  ['add_circle', 'add_circle'],
])

/** Preserve provider logos and icons without custom artwork. */
export function navigationIcon(icon: string): string
export function navigationIcon(icon: string | undefined): string | undefined
export function navigationIcon(icon: string | undefined): string | undefined {
  if (!icon) return icon
  const asset = navigationIcons.get(icon)
  return asset ? `img:/menu-icons/${asset}.svg` : icon
}
