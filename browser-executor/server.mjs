import crypto from "node:crypto";
import http from "node:http";
import net from "node:net";

import { operationSettings } from './settings.mjs';
import { readCredential } from './credential.mjs';

import { chromium } from "playwright";
import { SessionPool } from "./sessions.mjs";
import { BrowserLifecycle } from "./browser-lifecycle.mjs";
import { PDF_HTML_MAX_BYTES, renderStaticPdf } from "./pdf.mjs";

import {
  BrowserRequestError,
  assertHttpUrl,
  parseOptionalBoundedInt,
  parsePositiveInt,
  resolveTarget,
  safeReference,
  screenshotCaptureWidth,
  screenshotSlices,
} from "./lib.mjs";

const PORT = parsePositiveInt(process.env.PORT, 3000, 1, 65_535);
const AUTH_TOKEN = readCredential();
const NAVIGATION_TIMEOUT_MS =
  parsePositiveInt(process.env.BROWSER_NAVIGATION_TIMEOUT_SECONDS, 30, 5, 120) * 1_000;

const sessions = new SessionPool(32);
const browsers = new BrowserLifecycle(
  () => chromium.launch({ headless: true }),
  () => {
    console.error("browser disconnected unexpectedly; terminating for recovery");
    void shutdown(1);
  },
);
let proxy;
let pdfJobs = 0;

function sendJson(response, status, payload) {
  const body = Buffer.from(JSON.stringify(payload));
  response.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "content-length": body.length,
    "cache-control": "no-store",
  });
  response.end(body);
}

function ownerFrom(body) {
  const raw = body?.owner;
  const agentId = raw?.agent_id == null ? null : Number(raw.agent_id);
  const userId = raw?.user_id == null ? null : Number(raw.user_id);
  const taskId = raw?.task_id == null ? null : String(raw.task_id);
  const identity = agentId ?? userId;
  if ((agentId === null) === (userId === null) || !Number.isSafeInteger(identity) || identity <= 0 || (userId !== null && taskId !== null)) {
    throw new BrowserRequestError("invalid_owner", "A valid session owner is required.");
  }
  return { agent_id: agentId, user_id: userId, task_id: taskId };
}

function sameOwner(left, right) {
  return left.agent_id === right.agent_id && left.user_id === right.user_id && left.task_id === right.task_id;
}

async function readBody(request, maxBytes = 1_048_576) {
  const chunks = [];
  let size = 0;
  for await (const chunk of request) {
    size += chunk.length;
    if (size > maxBytes) {
      throw new BrowserRequestError("payload_too_large", "The request is too large.", 413);
    }
    chunks.push(chunk);
  }
  try {
    return JSON.parse(Buffer.concat(chunks).toString("utf8") || "{}");
  } catch {
    throw new BrowserRequestError("invalid_json", "The request body is invalid.");
  }
}

function sessionFor(body) {
  const session = sessions.get(String(body.session_id ?? ""));
  if (!session || !sameOwner(session.owner, ownerFrom(body))) {
    throw new BrowserRequestError("session_not_found", "The browser session was not found.", 404);
  }
  session.touchedAt = Date.now();
  return session;
}

async function closeSession(id) {
  await sessions.close(id);
}

async function installNetworkRouting(context) {
  await context.route("**/*", async (route) => {
    const requestUrl = route.request().url();
    if (
      requestUrl.startsWith("data:") ||
      requestUrl.startsWith("blob:") ||
      requestUrl.startsWith("about:")
    ) {
      await route.continue();
      return;
    }
    try {
      await assertHttpUrl(requestUrl);
      await route.continue();
    } catch {
      await route.abort("blockedbyclient");
    }
  });
}

async function startNetworkProxy() {
  const networkProxy = http.createServer((request, response) => {
    void (async () => {
      const { url, address } = await resolveTarget(request.url);
      const headers = { ...request.headers, host: url.host };
      delete headers["proxy-authorization"];
      const upstream = http.request(
        {
          host: address,
          port: url.port || 80,
          method: request.method,
          path: `${url.pathname}${url.search}`,
          headers,
        },
        (upstreamResponse) => {
          upstreamResponse.on("error", () => response.destroy());
          response.writeHead(
            upstreamResponse.statusCode || 502,
            upstreamResponse.statusMessage,
            upstreamResponse.headers,
          );
          upstreamResponse.pipe(response);
        },
      );
      response.on("error", () => upstream.destroy());
      request.on("error", () => upstream.destroy());
      upstream.on("error", () => response.destroy());
      request.pipe(upstream);
    })().catch(() => {
      response.writeHead(403, { connection: "close" });
      response.end();
    });
  });
  networkProxy.on("connect", (request, clientSocket, head) => {
    void (async () => {
      const { url, address } = await resolveTarget(`https://${request.url}`);
      const upstream = net.connect(Number(url.port || 443), address, () => {
        clientSocket.write("HTTP/1.1 200 Connection Established\r\n\r\n");
        if (head.length > 0) upstream.write(head);
        upstream.pipe(clientSocket);
        clientSocket.pipe(upstream);
      });
      clientSocket.on("error", () => upstream.destroy());
      upstream.on("error", () => clientSocket.destroy());
    })().catch(() => {
      clientSocket.end("HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n");
    });
  });
  networkProxy.on("clientError", (_error, socket) => socket.destroy());
  await new Promise((resolve, reject) => {
    networkProxy.once("error", reject);
    networkProxy.listen(0, "127.0.0.1", resolve);
  });
  return networkProxy;
}

async function pageSummary(session) {
  const metadata = await session.page.evaluate(() => {
    const meta = (...keys) => {
      for (const key of keys) {
        const value = document.querySelector(`meta[property="${key}"],meta[name="${key}"]`)?.content;
        if (value?.trim()) return value.replace(/\s+/g, ' ').trim();
      }
      return '';
    };
    return {
      description: meta('og:description', 'twitter:description', 'description').slice(0, 600),
      site_name: meta('og:site_name').slice(0, 160),
    };
  });
  return {
    session_id: session.id,
    url: session.page.url(),
    title: await session.page.title(),
    ...metadata,
    revision: session.revision,
  };
}

async function waitForDocument(page) {
  await page.waitForTimeout(250);
  await page.waitForLoadState("domcontentloaded", { timeout: 10_000 }).catch(() => {});
  await page.locator("body").waitFor({ state: "attached", timeout: 10_000 });
}

async function contentResult(session, config, offset = 0, requestedMaxChars = config.content_max_chars) {
  await waitForDocument(session.page);
  const content = await session.page.locator("body").ariaSnapshot({
    timeout: 10_000,
    mode: "ai",
  });
  const start = Math.min(Math.max(0, Number.parseInt(String(offset), 10) || 0), content.length);
  const maxChars = Math.min(
    config.content_max_chars,
    Math.max(1_000, Number.parseInt(String(requestedMaxChars), 10) || config.content_max_chars),
  );
  const end = Math.min(content.length, start + maxChars);
  return {
    ...(await pageSummary(session)),
    content: content.slice(start, end),
    start,
    end,
    total: content.length,
    truncated: end < content.length,
    next_offset: end < content.length ? end : null,
  };
}

async function primeLazyContent(page, config) {
  for (let index = 0; index < config.screenshot_max_tiles; index += 1) {
    const y = index * config.screenshot_tile_height;
    await page.evaluate((scrollY) => window.scrollTo(0, scrollY), y);
    await page.waitForTimeout(100);
  }
  await page.evaluate(() => window.scrollTo(0, 0));
}

function captureDimensions(body) {
  const config = body.settings;
  const maxWidth = body.max_width == null
    ? null
    : parsePositiveInt(body.max_width, config.viewport_width, 1, config.viewport_width);
  const maxHeight = body.max_height == null
    ? null
    : parsePositiveInt(body.max_height, config.viewport_height, 1, config.viewport_height);
  return {
    maxWidth,
    maxHeight,
    viewportWidth: maxWidth ?? config.viewport_width,
    viewportHeight: maxHeight ?? config.viewport_height,
  };
}

function requestedViewport(body, fallback) {
  return {
    width: parseOptionalBoundedInt(
      body.viewport_width,
      320,
      3_840,
      "invalid_viewport",
    ) ?? fallback.width,
    height: parseOptionalBoundedInt(
      body.viewport_height,
      240,
      2_160,
      "invalid_viewport",
    ) ?? fallback.height,
  };
}

async function applyRequestedViewport(session, body) {
  const config = body.settings;
  if (body.viewport_width == null && body.viewport_height == null) return;
  const current = session.page.viewportSize() ?? {
    width: config.viewport_width,
    height: config.viewport_height,
  };
  await session.page.setViewportSize(requestedViewport(body, current));
}

async function screenshotResult(session, config, imageFormat, maxWidth = null, maxHeight = null) {
  const format = imageFormat === "png" ? "png" : "jpeg";
  await waitForDocument(session.page);
  if (maxHeight == null) await primeLazyContent(session.page, config);
  const dimensions = await session.page.evaluate(() => ({
    width: Math.max(
      document.documentElement.scrollWidth,
      document.body?.scrollWidth ?? 0,
      document.documentElement.clientWidth,
    ),
    height: Math.max(
      document.documentElement.scrollHeight,
      document.body?.scrollHeight ?? 0,
      document.documentElement.clientHeight,
    ),
  }));
  const viewportWidth = session.page.viewportSize()?.width ?? config.viewport_width;
  const width = screenshotCaptureWidth(dimensions.width, viewportWidth, maxWidth);
  const tiling = maxHeight == null
    ? screenshotSlices(dimensions.height, config.screenshot_tile_height, config.screenshot_max_tiles)
    : {
        slices: [{ index: 0, y: 0, height: Math.min(maxHeight, dimensions.height) }],
        truncated: dimensions.height > maxHeight,
      };
  const parts = [];
  let bytes = 0;
  let bytesTruncated = false;
  for (const slice of tiling.slices) {
    const data = await session.page.screenshot({
      type: format,
      quality: format === "jpeg" ? 80 : undefined,
      animations: "disabled",
      caret: "hide",
      clip: { x: 0, y: slice.y, width, height: slice.height },
    });
    if (bytes + data.length > config.screenshot_max_total_bytes) {
      bytesTruncated = true;
      break;
    }
    bytes += data.length;
    parts.push({
      index: slice.index,
      y: slice.y,
      width,
      height: slice.height,
      mime_type: `image/${format}`,
      data: data.toString("base64"),
    });
  }
  const capturedHeight = parts.reduce((height, part) => height + part.height, 0);
  return {
    ...(await pageSummary(session)),
    page_width: dimensions.width,
    page_height: dimensions.height,
    captured_height: capturedHeight,
    truncated: tiling.truncated || bytesTruncated || capturedHeight < dimensions.height,
    parts,
  };
}

async function requestedOutput(session, body) {
  const dimensions = captureDimensions(body);
  return body.output === "screenshot"
    ? screenshotResult(session, body.settings, body.image_format, dimensions.maxWidth, dimensions.maxHeight)
    : contentResult(session, body.settings, body.offset, body.max_chars);
}

async function createSession(owner, viewport, config) {
  const browser = await browsers.get();
  const context = await browser.newContext({
    viewport,
    serviceWorkers: "block",
    acceptDownloads: false,
    proxy: { server: `http://127.0.0.1:${proxy.address().port}` },
  });
  try {
    await installNetworkRouting(context);
    const page = await context.newPage();
    page.setDefaultTimeout(15_000);
    page.setDefaultNavigationTimeout(NAVIGATION_TIMEOUT_MS);
    return {
      id: crypto.randomUUID(), owner, context, page,
      revision: 1, touchedAt: Date.now(),
      idleTtlMs: config.session_ttl_seconds * 1_000,
    };
  } catch (error) {
    await context.close().catch(() => {});
    throw error;
  }
}

async function open(body) {
  const owner = ownerFrom(body);
  const url = await assertHttpUrl(body.url);
  const dimensions = captureDimensions(body);
  const viewport = requestedViewport(body, {
    width: dimensions.viewportWidth, height: dimensions.viewportHeight,
  });
  return sessions.create(
    () => createSession(owner, viewport, body.settings),
    async (session) => {
      await session.page.goto(url.href, { waitUntil: "domcontentloaded" });
      return requestedOutput(session, body);
    },
    body.settings.max_sessions,
  );
}

async function renderHtml(body) {
  const config = body.settings;
  const owner = ownerFrom(body);
  const dimensions = captureDimensions(body);
  const encoded = String(body.html_base64 ?? "");
  const html = Buffer.from(encoded, "base64");
  if (!encoded || html.length === 0 || html.length > config.html_max_bytes) {
    throw new BrowserRequestError("payload_too_large", "The HTML payload is too large.", 413);
  }
  return sessions.create(
    () => createSession(owner, { width: dimensions.viewportWidth, height: dimensions.viewportHeight }, config),
    async (session) => {
      await session.page.setContent(html.toString("utf8"), { waitUntil: "domcontentloaded" });
      return screenshotResult(session, config, "jpeg", dimensions.maxWidth, dimensions.maxHeight);
    },
    config.max_sessions,
  );
}

async function performAction(body) {
  return sessions.run(sessionFor(body), (session) => {
    session.idleTtlMs = body.settings.session_ttl_seconds * 1_000;
    return performSessionAction(session, body);
  });
}

async function performSessionAction(session, body) {
  const action = String(body.action ?? "");
  await applyRequestedViewport(session, body);
  if (action === "content") return contentResult(session, body.settings, body.offset, body.max_chars);
  if (action === "screenshot") return screenshotResult(session, body.settings, body.image_format);
  if (action === "navigate") {
    const url = await assertHttpUrl(body.url);
    await session.page.goto(url.href, { waitUntil: "domcontentloaded" });
  } else if (action === "click") {
    await session.page.locator(`aria-ref=${safeReference(body.ref)}`).click();
  } else if (action === "type") {
    const locator = session.page.locator(`aria-ref=${safeReference(body.ref)}`);
    const text = String(body.text ?? "");
    if (text.length > 20_000) {
      throw new BrowserRequestError("text_too_long", "The input text is too long.");
    }
    if (body.submit === true) {
      await locator.fill(text);
      await locator.press("Enter");
    } else {
      await locator.fill(text);
    }
  } else if (action === "press") {
    const key = String(body.key ?? "");
    if (!/^[A-Za-z0-9+_-]{1,40}$/.test(key)) {
      throw new BrowserRequestError("invalid_key", "The keyboard key is invalid.");
    }
    await session.page.keyboard.press(key);
  } else if (action === "scroll") {
    const deltaY = Math.min(20_000, Math.max(-20_000, Number(body.delta_y) || 0));
    await session.page.mouse.wheel(0, deltaY);
  } else if (action === "back") {
    await session.page.goBack({ waitUntil: "domcontentloaded" });
  } else {
    throw new BrowserRequestError("invalid_action", "The browser action is invalid.");
  }
  session.revision += 1;
  return requestedOutput(session, body);
}

async function close(body) {
  const session = await sessionFor(body);
  await closeSession(session.id);
  return { closed: true, session_id: session.id };
}

async function closeOwner(body) {
  const owner = ownerFrom(body);
  const ownedIds = [...sessions.entries()]
    .filter(([, session]) => sameOwner(session.owner, owner))
    .map(([id]) => id);
  await Promise.all(ownedIds.map(closeSession));
  return { closed: ownedIds.length };
}

async function route(request, response) {
  if (request.url === "/health" && request.method === "GET") {
    sendJson(response, shuttingDown ? 503 : 200, { status: shuttingDown ? "unavailable" : "ok" });
    return;
  }
  if (
    request.headers["x-galaris-browser-token"] !== AUTH_TOKEN ||
    AUTH_TOKEN.length < 16
  ) {
    sendJson(response, 401, { error: { code: "unauthorized", message: "Unauthorized." } });
    return;
  }
  if (request.method !== "POST") {
    throw new BrowserRequestError("not_found", "Not found.", 404);
  }
  const body = await readBody(request, request.url === '/v1/render-pdf' ? 2 * PDF_HTML_MAX_BYTES : 1_048_576);
  body.settings = operationSettings(body.settings);
  if (request.url === "/v1/open") {
    sendJson(response, 200, await open(body));
  } else if (request.url === "/v1/render-html") {
    sendJson(response, 200, await renderHtml(body));
  } else if (request.url === '/v1/render-pdf') {
    if (pdfJobs >= 2) throw new BrowserRequestError('capacity_reached', 'PDF capacity has been reached.', 503);
    pdfJobs += 1;
    try {
      const pdf = await renderStaticPdf(await browsers.get(), body.html, { firstPageOnly: body.first_page_only === true });
      response.writeHead(200, { 'content-type': 'application/pdf', 'content-length': pdf.length, 'cache-control': 'no-store' });
      response.end(pdf);
    } finally {
      pdfJobs -= 1;
    }
  } else if (request.url === "/v1/action") {
    sendJson(response, 200, await performAction(body));
  } else if (request.url === "/v1/close") {
    sendJson(response, 200, await close(body));
  } else if (request.url === "/v1/close-owner") {
    sendJson(response, 200, await closeOwner(body));
  } else {
    throw new BrowserRequestError("not_found", "Not found.", 404);
  }
}

proxy = await startNetworkProxy();
const server = http.createServer((request, response) => {
  route(request, response).catch((error) => {
    const known = error instanceof BrowserRequestError;
    const errorType =
      error && typeof error === "object" && "name" in error
        ? String(error.name)
        : typeof error;
    console.error(`browser operation failed: ${errorType}`);
    sendJson(response, known ? error.status : 502, {
      error: {
        code: known ? error.code : "browser_failed",
        message:
          known || process.env.BROWSER_DEBUG_ERRORS === "true"
            ? String(error?.message ?? "The browser operation failed.")
            : "The browser operation failed.",
      },
    });
  });
});

const sweeper = setInterval(() => {
  void sessions.sweep(Date.now())
    .then(() => browsers.closeIfIdle(sessions.occupied > 0 || pdfJobs > 0))
    .catch(() => console.error("browser session cleanup failed"));
}, 10_000);
sweeper.unref();

let shuttingDown = false;
async function shutdown(exitCode = 0) {
  if (shuttingDown) return;
  shuttingDown = true;
  clearInterval(sweeper);
  // Neither browser cleanup nor open proxy sockets may keep a failed service
  // alive forever. Exiting allows the container restart policy to recover it.
  const deadline = setTimeout(() => process.exit(exitCode), 3000);
  server.close();
  server.closeAllConnections();
  proxy.close();
  try {
    await Promise.allSettled([...sessions.keys()].map(closeSession));
    await browsers.stop();
  } finally {
    clearTimeout(deadline);
    process.exit(exitCode);
  }
}

process.on("SIGTERM", () => void shutdown(0));
process.on("SIGINT", () => void shutdown(0));

server.listen(PORT, "0.0.0.0");
