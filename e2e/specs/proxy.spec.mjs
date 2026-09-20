import { test, expect } from '@playwright/test'

// Simulate the headers supplied by the external TLS terminator. Requests pass
// through the production Nginx template and the real Uvicorn/FastAPI routes.
for (const { proto, expectedScheme } of [
  { proto: 'https', expectedScheme: 'https' },
  { proto: 'http', expectedScheme: 'http' },
  { proto: undefined, expectedScheme: 'http' },
  { proto: 'invalid', expectedScheme: 'http' },
]) {
  test(`API redirects preserve the external scheme (${proto ?? 'direct HTTP'}) and port`, async ({ request }) => {
    const response = await request.get('/api/chat/status/', {
      headers: { Host: 'localhost:8443', ...(proto ? { 'X-Forwarded-Proto': proto } : {}) },
      maxRedirects: 0,
    })
    expect(response.status()).toBe(307)
    expect(response.headers().location).toBe(`${expectedScheme}://localhost:8443/api/chat/status`)
  })
}

test('Socket.IO polling remains available behind the production proxy', async ({ request }) => {
  const response = await request.get('/socket.io/?EIO=4&transport=polling', {
    headers: { Host: 'localhost:8443', 'X-Forwarded-Proto': 'https' },
  })
  expect(response.status()).toBe(200)
  expect(await response.text()).toMatch(/^0\{"sid":/)
})
