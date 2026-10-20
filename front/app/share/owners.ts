/** Owner identity shared by resource editors and filters; authorization stays in each domain. */
export interface OwnerOption {
  kind: 'user' | 'agent'
  id: number
  label: string
  subtitle?: string
  avatar_url?: string | null
  has_avatar?: boolean
  is_current_user?: boolean
}

export function ownerKey(owner: { kind: string; id: number }): string {
  return `${owner.kind}:${owner.id}`
}
