import { Dialog, type QBtnProps } from 'quasar'
import ConfirmationDialog from './components/ConfirmationDialog.vue'

export interface ConfirmationDialogOptions {
  title?: string
  message: string
  ok?: boolean | string | QBtnProps
  cancel?: boolean | string | QBtnProps
  focus?: 'ok' | 'cancel' | 'none'
  color?: string
}

/** Keep Quasar's outcome callbacks while sharing the application's title bar. */
export function showConfirmationDialog(options: ConfirmationDialogOptions) {
  return Dialog.create({ component: ConfirmationDialog, componentProps: options })
}
