import { inject, provide, type InjectionKey } from 'vue'

const referencePath: InjectionKey<() => readonly string[]> = Symbol('document reference path')

export function useDocumentReferencePath(): () => readonly string[] {
  return inject(referencePath, () => [])
}

export function provideDocumentReferencePath(path: () => readonly string[]): void {
  provide(referencePath, path)
}
