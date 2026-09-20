import { BrowserRequestError, parseOptionalBoundedInt } from './lib.mjs';

// Hard bounds protect the executor independently of the backend. Preferences
// travel with an authenticated operation and never mutate another request.
const fields = {
  session_ttl_seconds: [120, 10, 3_600],
  max_sessions: [32, 1, 256],
  content_max_chars: [20_000, 1_000, 200_000],
  html_max_bytes: [500_000, 10_000, 750_000],
  screenshot_tile_height: [3_000, 500, 10_000],
  screenshot_max_tiles: [8, 1, 30],
  screenshot_max_total_bytes: [25_000_000, 1_000_000, 100_000_000],
  viewport_width: [1_440, 320, 3_840],
  viewport_height: [900, 240, 2_160],
};

export function operationSettings(value = {}) {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new BrowserRequestError('invalid_settings', 'Invalid browser settings.');
  }
  return Object.fromEntries(Object.entries(fields).map(([name, [fallback, min, max]]) => [
    name, parseOptionalBoundedInt(value[name], min, max, 'invalid_settings') ?? fallback,
  ]));
}
