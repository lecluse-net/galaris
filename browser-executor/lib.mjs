import dns from "node:dns/promises";
import net from "node:net";

const ALLOWED_SCHEMES = new Set(["http:", "https:"]);
const DNS_CACHE_TTL_MS = 30_000;
const dnsCache = new Map();

export class BrowserRequestError extends Error {
  constructor(code, message, status = 400) {
    super(message);
    this.name = "BrowserRequestError";
    this.code = code;
    this.status = status;
  }
}

export function parsePositiveInt(value, fallback, minimum, maximum) {
  const parsed = Number.parseInt(String(value ?? ""), 10);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.min(maximum, Math.max(minimum, parsed));
}

export function parseOptionalBoundedInt(value, minimum, maximum, code) {
  if (value == null) return null;
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed < minimum || parsed > maximum) {
    throw new BrowserRequestError(code, "The requested value is outside its allowed range.");
  }
  return parsed;
}

export function parseUrl(raw) {
  if (typeof raw !== "string" || raw.length === 0 || raw.length > 4096) {
    throw new BrowserRequestError("invalid_url", "A valid URL is required.");
  }
  let url;
  try {
    url = new URL(raw);
  } catch {
    throw new BrowserRequestError("invalid_url", "The URL is invalid.");
  }
  if (!ALLOWED_SCHEMES.has(url.protocol) || url.username || url.password) {
    throw new BrowserRequestError(
      "invalid_url",
      "Only HTTP(S) URLs without embedded credentials are accepted.",
    );
  }
  if (!url.hostname) {
    throw new BrowserRequestError("invalid_url", "The URL hostname is missing.");
  }
  return url;
}

function dnsHostname(hostname) {
  return hostname.startsWith("[") && hostname.endsWith("]")
    ? hostname.slice(1, -1)
    : hostname;
}

async function resolveAddresses(hostname) {
  const lookupName = dnsHostname(hostname);
  if (net.isIP(lookupName)) return [lookupName];
  const now = Date.now();
  const cached = dnsCache.get(lookupName);
  if (cached && cached.expiresAt > now) return cached.addresses;
  let records;
  try {
    records = await dns.lookup(lookupName, { all: true, verbatim: true });
  } catch {
    throw new BrowserRequestError("dns_failed", "The destination could not be resolved.", 502);
  }
  const addresses = records.map((record) => record.address);
  dnsCache.set(lookupName, { addresses, expiresAt: now + DNS_CACHE_TTL_MS });
  return addresses;
}

export async function resolveTarget(raw) {
  const url = parseUrl(raw);
  const addresses = await resolveAddresses(url.hostname);
  if (addresses.length === 0) {
    throw new BrowserRequestError("dns_failed", "The destination could not be resolved.", 502);
  }
  // Docker services, including this sidecar, commonly listen on IPv4 only while
  // localhost resolves to ::1 first. Prefer an available IPv4 record and retain
  // IPv6 support for IPv6-only names and literals.
  return { url, address: addresses.find((address) => net.isIPv4(address)) ?? addresses[0] };
}

export async function assertHttpUrl(raw) {
  return (await resolveTarget(raw)).url;
}

export function screenshotSlices(totalHeight, tileHeight, maxTiles) {
  const boundedHeight = Math.max(1, Math.floor(totalHeight));
  const boundedTile = Math.max(1, Math.floor(tileHeight));
  const count = Math.min(maxTiles, Math.ceil(boundedHeight / boundedTile));
  const slices = [];
  for (let index = 0; index < count; index += 1) {
    const y = index * boundedTile;
    slices.push({
      index,
      y,
      height: Math.min(boundedTile, boundedHeight - y),
    });
  }
  return {
    slices,
    capturedHeight: slices.reduce((height, slice) => height + slice.height, 0),
    truncated: count * boundedTile < boundedHeight,
  };
}

export function screenshotCaptureWidth(documentWidth, viewportWidth, maxWidth = null) {
  return Math.min(maxWidth ?? viewportWidth, Math.max(1, documentWidth));
}

export function safeReference(raw) {
  const ref = String(raw ?? "").trim();
  if (!/^e[0-9]+$/.test(ref)) {
    throw new BrowserRequestError("invalid_ref", "The element reference is invalid.");
  }
  return ref;
}
