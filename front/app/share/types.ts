import type { SharingRecipient, SharingState as SharingPresentation } from './sharing'

export interface SharingState extends SharingPresentation {
  lock_version: number
  can_manage: boolean
}
export interface SharingUpdate {
  level: 'private' | 'groups' | 'public'
  can_write: boolean
  grants: Pick<SharingRecipient, 'kind' | 'id' | 'can_write'>[]
  expected_lock_version: number
}
export interface SingleGrantUpdate {
  kind: SharingRecipient['kind']
  id: number
  can_write: boolean | null
  expected_lock_version: number
}
export type Collaborator = SharingRecipient
