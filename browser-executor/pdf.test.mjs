import assert from 'node:assert/strict';
import http from 'node:http';
import { once } from 'node:events';
import test from 'node:test';
import { chromium } from 'playwright';
import { PDF_HTML_MAX_BYTES, renderStaticPdf } from './pdf.mjs';

test('static PDF preserves pagination and inline images without scripts, network or retained contexts', { timeout: 30_000 }, async () => {
  let requests = 0;
  const server = http.createServer((_request, response) => { requests += 1; response.end('external'); }).listen(0, '127.0.0.1');
  await once(server, 'listening');
  const browser = await chromium.launch({ headless: true });
  try {
    const url = `http://127.0.0.1:${server.address().port}`;
    const image = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aX9sAAAAASUVORK5CYII=';
    const pdf = await renderStaticPdf(browser, `<html><head><title>PDF export</title><link rel="stylesheet" href="${url}"></head><body><h1>Été — rapport</h1><img src="data:image/png;base64,${image}"><p style="break-before:page">Second page</p><script>while(true){}</script></body></html>`);
    assert.equal(pdf.subarray(0, 5).toString(), '%PDF-');
    assert.match(pdf.toString('latin1'), /\/Count 2\b/);
    assert.match(pdf.toString('latin1'), /\/Subtype \/Image/);
    assert.equal(requests, 0);
    assert.equal(browser.contexts().length, 0);
    const firstPage = await renderStaticPdf(browser, '<h1>Beginning</h1><p style="break-before:page">End</p>', { firstPageOnly: true });
    assert.match(firstPage.toString('latin1'), /\/Count 1\b/);
    assert.doesNotMatch(firstPage.toString('latin1'), /\/Count 2\b/);
    await assert.rejects(renderStaticPdf(browser, '<img src="data:image/png;base64,broken">'));
    assert.equal(browser.contexts().length, 0);
    await assert.rejects(renderStaticPdf(browser, 'x'.repeat(PDF_HTML_MAX_BYTES + 1)), { code: 'invalid_pdf_html' });
    assert.equal(browser.contexts().length, 0);
  } finally {
    await browser.close();
    server.close();
  }
});
