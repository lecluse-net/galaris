import { BrowserRequestError } from './lib.mjs';

export const SVG_MAX_BYTES = 5 * 1_048_576;
const MAX_WIDTH = 320;
const MAX_HEIGHT = 320;

/** Decode SVG as an inert image in a disposable offline context. */
export async function renderSvgThumbnail(browser, { data }) {
  if (typeof data !== 'string' || data.length > Math.ceil(SVG_MAX_BYTES / 3) * 4
    || !/^[A-Za-z0-9+/]*={0,2}$/.test(data)) {
    throw new BrowserRequestError('invalid_svg', 'Invalid or oversized SVG.', 413);
  }
  const bytes = Buffer.from(data, 'base64');
  if (!bytes.length || bytes.length > SVG_MAX_BYTES) {
    throw new BrowserRequestError('invalid_svg', 'Invalid or oversized SVG.', 413);
  }
  const context = await browser.newContext({
    javaScriptEnabled: false, offline: true, serviceWorkers: 'block', acceptDownloads: false,
    viewport: { width: MAX_WIDTH, height: MAX_HEIGHT }, deviceScaleFactor: 1,
  });
  const deadline = setTimeout(() => { void context.close().catch(() => {}); }, 30_000);
  try {
    await context.route('**/*', route => route.abort('blockedbyclient'));
    const page = await context.newPage();
    await page.setContent('<body style="margin:0"><img style="display:block"></body>');
    try {
      await page.evaluate(async ({ data, maxWidth, maxHeight }) => {
        const image = document.querySelector('img');
        image.src = `data:image/svg+xml;base64,${data}`;
        await image.decode();
        const { naturalWidth: width, naturalHeight: height } = image;
        if (!width || !height) throw new Error('Invalid SVG dimensions');
        const scale = Math.min(1, maxWidth / width, maxHeight / height);
        image.width = Math.max(1, Math.floor(width * scale));
        image.height = Math.max(1, Math.floor(height * scale));
      }, { data, maxWidth: MAX_WIDTH, maxHeight: MAX_HEIGHT });
    } catch {
      throw new BrowserRequestError('invalid_svg', 'Unable to decode the SVG image.', 422);
    }
    const png = await page.locator('img').screenshot({ type: 'png', omitBackground: true, timeout: 20_000 });
    if (png.length > SVG_MAX_BYTES) throw new BrowserRequestError('svg_too_large', 'The thumbnail is too large.', 413);
    return png;
  } finally {
    clearTimeout(deadline);
    await context.close();
  }
}
