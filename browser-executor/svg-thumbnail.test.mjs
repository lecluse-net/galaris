import assert from 'node:assert/strict';
import http from 'node:http';
import { once } from 'node:events';
import test from 'node:test';
import { chromium } from 'playwright';
import { SVG_MAX_BYTES, renderSvgThumbnail } from './svg-thumbnail.mjs';

test('SVG thumbnails preserve alpha and fit dimensions without running scripts or external requests', { timeout: 30_000 }, async () => {
  let requests = 0;
  const server = http.createServer((_request, response) => { requests++; response.end('external'); }).listen(0, '127.0.0.1');
  await once(server, 'listening');
  const browser = await chromium.launch({ headless: true });
  try {
    const url = `http://127.0.0.1:${server.address().port}`;
    for (const [width, height, expected] of [[80, 40, [80, 40]], [1200, 600, [320, 160]], [600, 900, [213, 320]]]) {
      const data = Buffer.from(`<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}"><rect width="${width / 2}" height="${height}" fill="red"/><image href="${url}/image" width="10" height="10"/><script>fetch('${url}/script'); while(true){}</script></svg>`).toString('base64');
      const png = await renderSvgThumbnail(browser, { data });
      assert.equal(png.subarray(1, 4).toString(), 'PNG');
      assert.deepEqual([png.readUInt32BE(16), png.readUInt32BE(20)], expected);
      assert.equal(browser.contexts().length, 0);
      const context = await browser.newContext();
      try {
        const page = await context.newPage();
        const pixels = await page.evaluate(async data => {
          const image = new Image(); image.src = `data:image/png;base64,${data}`; await image.decode();
          const canvas = document.createElement('canvas'); canvas.width = image.width; canvas.height = image.height;
          const ctx = canvas.getContext('2d'); ctx.drawImage(image, 0, 0);
          return [0.25, 0.75].map(ratio => [...ctx.getImageData(Math.floor(image.width * ratio), Math.floor(image.height / 2), 1, 1).data]);
        }, png.toString('base64'));
        assert.deepEqual(pixels, [[255, 0, 0, 255], [0, 0, 0, 0]]);
      } finally { await context.close(); }
    }
    assert.equal(requests, 0);
    for (const data of ['broken!', '', Buffer.from('not SVG').toString('base64'), Buffer.alloc(SVG_MAX_BYTES + 1).toString('base64')]) {
      await assert.rejects(renderSvgThumbnail(browser, { data }), { code: 'invalid_svg' });
      assert.equal(browser.contexts().length, 0);
    }
  } finally { await browser.close(); server.close(); }
});
