interface CleanupContribution { default: { key: string; run: () => Promise<unknown> } }
const modules = import.meta.glob<CleanupContribution>('../../../app/*/logCleanup.ts', { eager: true })
const contributions = Object.values(modules).map(module => module.default)

export const logCleanupService = {
  async cleanup(target: string): Promise<void> {
    const matches = contributions.filter(contribution => contribution.key === target)
    if (matches.length !== 1) throw new Error(`Unknown or ambiguous cleanup contribution: ${target}`)
    await matches[0]!.run()
  },
}
