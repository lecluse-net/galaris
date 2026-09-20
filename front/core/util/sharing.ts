/** Resource-independent sharing form. Persistence and authorization belong to its host. */
export type SharingLevel = 'private' | 'groups' | 'public'
export interface SharingRecipient {
  kind: 'agent' | 'user' | 'team'
  id: number
  label: string
  can_write: boolean
  group_ids?: number[]
  avatar_url?: string | null
  has_avatar?: boolean
}
export interface SharingState {
  owner: SharingRecipient | null
  level: SharingLevel
  can_write: boolean
  grants: SharingRecipient[]
  options: SharingRecipient[]
  owner_groups: SharingRecipient[]
}
export interface SharingChoice extends SharingRecipient {
  can_grant_read: boolean
  can_grant_write: boolean
}
export interface SharingDraft {
  level: SharingLevel
  can_write: boolean
  grants: Pick<SharingRecipient, 'kind' | 'id' | 'can_write'>[]
}
