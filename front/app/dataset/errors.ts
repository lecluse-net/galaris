import { isAxiosError } from 'axios'
export function errorMessage(error: unknown, fallback: string): string {
  if (!isAxiosError(error)) return error instanceof SyntaxError ? error.message : fallback
  const body: unknown = error.response?.data
  if (body && typeof body === 'object' && 'detail' in body) {
    const detail: unknown = body.detail
    if (typeof detail === 'string') return detail
    if (detail && typeof detail === 'object' && 'message' in detail && typeof detail.message === 'string') return detail.message
    if (Array.isArray(detail)) return detail.map((item: unknown) => item && typeof item === 'object' && 'msg' in item && typeof item.msg === 'string' ? item.msg : fallback).join('\n')
  }
  return fallback
}
