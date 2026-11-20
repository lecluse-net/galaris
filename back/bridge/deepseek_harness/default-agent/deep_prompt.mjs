import { readFileSync } from 'node:fs';

export const name = 'galaris-deep-prompt';
export const inject = ['systemPrompt'];

export function apply(ctx) {
  const path = process.env.GALARIS_DEEP_PROFILE_PATH;
  if (!path) return;
  const text = readFileSync(path, 'utf8');
  if (!text) return;
  ctx.systemPrompt.section({
    name: 'galaris:deep-profile',
    order: ctx.systemPrompt.getSectionOrder('DEPLOYMENT_PERSONA_PREFIX'),
    text,
    interpolate: false,
  });
}
