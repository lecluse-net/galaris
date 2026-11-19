import { BrowserRequestError } from './lib.mjs';

const MAX_SOURCE_BYTES = 512 * 1024;

/** Load the signed entry point in a fresh browser context without application credentials. */
export async function qualifyPluginModule(browser, encoded) {
  if (typeof encoded !== 'string' || encoded.length > Math.ceil(MAX_SOURCE_BYTES / 3) * 4) {
    throw new BrowserRequestError('invalid_plugin_module', 'Invalid document plugin module.', 422);
  }
  const source = Buffer.from(encoded, 'base64');
  if (!source.length || source.length > MAX_SOURCE_BYTES || source.toString('base64') !== encoded) {
    throw new BrowserRequestError('invalid_plugin_module', 'Invalid document plugin module.', 422);
  }
  const context = await browser.newContext({ offline: true, serviceWorkers: 'block', acceptDownloads: false });
  const deadline = setTimeout(() => { void context.close().catch(() => {}); }, 5_000);
  try {
    const origin = 'https://qualification.invalid';
    await context.route('**/*', route => {
      if (route.request().url() === origin + '/') {
        return route.fulfill({ contentType: 'text/html', body: '<!doctype html><title>Plugin qualification</title>',
          headers: { 'content-security-policy': "default-src 'none'; script-src 'self'; base-uri 'none'; form-action 'none'" } });
      }
      if (route.request().url() === origin + '/module.mjs') {
        return route.fulfill({ contentType: 'text/javascript', body: source });
      }
      return route.abort('blockedbyclient');
    });
    const page = await context.newPage();
    await page.goto(origin);
    const hasFactory = await page.evaluate(async () => typeof (await import('/module.mjs')).createFormat === 'function');
    if (!hasFactory) throw new Error('Missing document plugin factory');
  } catch {
    // Return a stable diagnostic without exposing publisher code or arbitrary exception text.
    throw new BrowserRequestError('invalid_plugin_module', 'Chromium could not load the document plugin factory.', 422);
  } finally {
    clearTimeout(deadline);
    await context.close().catch(() => {});
  }
}
