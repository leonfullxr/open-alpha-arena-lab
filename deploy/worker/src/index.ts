import { createRemoteJWKSet, jwtVerify, type JWTPayload } from "jose";

const ORIGIN = "https://arena-origin.leonfuller.com";
const PUBLIC_ROOT = "/api/v1/public";
const ID = "[A-Za-z0-9_-]{1,128}";
const PUBLIC_PATHS = [
  new RegExp(`^${PUBLIC_ROOT}/competitions$`),
  new RegExp(`^${PUBLIC_ROOT}/competitions/${ID}$`),
  new RegExp(`^${PUBLIC_ROOT}/competitions/${ID}/(?:equity|chart|leaderboard|metrics|events|decisions|positions|trades|export|stream)$`),
  new RegExp(`^${PUBLIC_ROOT}/competitions/${ID}/rules$`),
  new RegExp(`^${PUBLIC_ROOT}/competitions/${ID}/funding$`),
  new RegExp(`^${PUBLIC_ROOT}/funding/evidence/${ID}$`),
  new RegExp(`^${PUBLIC_ROOT}/models/${ID}$`),
  new RegExp(`^${PUBLIC_ROOT}/decisions/${ID}/artifact$`),
  new RegExp(`^${PUBLIC_ROOT}/ticker$`),
  new RegExp(`^${PUBLIC_ROOT}/status$`),
];
const ADMIN_READ_PATHS = [
  /^\/api\/v1\/admin\/status$/,
  /^\/api\/v1\/admin\/competitions$/,
  new RegExp(`^/api/v1/admin/competitions/${ID}$`),
  /^\/api\/v1\/admin\/providers$/,
  /^\/api\/v1\/admin\/prompts$/,
];
const ADMIN_WRITE_PATHS = [
  /^\/api\/v1\/admin\/competitions$/,
  new RegExp(`^/api/v1/admin/competitions/${ID}/(?:start|pause|resume|finish)$`),
  /^\/api\/v1\/admin\/providers$/,
  new RegExp(`^/api/v1/admin/providers/${ID}/test$`),
  /^\/api\/v1\/admin\/prompts$/,
];
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const FORWARDED_REQUEST_HEADERS = ["accept", "accept-language", "content-type", "origin", "if-none-match", "if-modified-since", "range", "last-event-id"];
const FORWARDED_RESPONSE_HEADERS = ["accept-ranges", "cache-control", "content-disposition", "content-length", "content-range", "content-type", "etag", "last-modified", "retry-after", "vary"];

function json(status: number, code: string): Response {
  return Response.json({ error: code }, { status, headers: { "cache-control": "no-store" } });
}

function safePath(pathname: string): boolean {
  return !pathname.includes("%") && !pathname.includes("\\") && !pathname.includes("//") &&
    !pathname.split("/").some((segment) => segment === "." || segment === "..");
}

function validPublicPath(pathname: string): boolean {
  return PUBLIC_PATHS.some((pattern) => pattern.test(pathname));
}

function boundedQuery(url: URL): boolean {
  const pathname = url.pathname;
  const allowed = pathname === `${PUBLIC_ROOT}/ticker`
    ? new Set(["competition_id"])
    : pathname === `${PUBLIC_ROOT}/competitions`
      ? new Set(["limit", "offset"])
    : pathname.endsWith("/events")
      ? new Set(["after", "limit"])
      : pathname.endsWith("/export")
        ? new Set(["limit", "offset"])
      : pathname.endsWith("/chart")
        ? new Set(["range", "points"])
      : pathname.endsWith("/funding")
        ? new Set(["limit", "offset", "agent_id", "symbol"])
        : /\/(?:equity|trades|positions|decisions)$/.test(pathname)
          ? new Set(["limit", "offset", "agent_id", "symbol", ...(pathname.endsWith("/positions") ? ["include_closed"] : [])])
          : new Set<string>();
  const queryKeys: string[] = [];
  url.searchParams.forEach((_value, key) => queryKeys.push(key));
  for (const key of queryKeys) {
    if (!allowed.has(key) || url.searchParams.getAll(key).length !== 1) return false;
  }
  if (pathname === `${PUBLIC_ROOT}/ticker`) {
    const competitionId = url.searchParams.get("competition_id");
    return competitionId === null || UUID.test(competitionId);
  }
  if (pathname.endsWith("/chart")) {
    const range = url.searchParams.get("range");
    const points = url.searchParams.get("points");
    if (range !== null && range !== "ALL" && range !== "72H" && range !== "24H") return false;
    if (points !== null && (!/^\d{1,3}$/.test(points) || Number(points) < 2 || Number(points) > 400)) return false;
  }
  for (const key of ["agent_id", "symbol"] as const) {
    const value = url.searchParams.get(key);
    if (value !== null && !(key === "agent_id" ? new RegExp(`^${ID}$`).test(value) : /^[A-Z0-9._-]{1,24}$/.test(value))) return false;
  }
  const includeClosed = url.searchParams.get("include_closed");
  if (includeClosed !== null && includeClosed !== "true" && includeClosed !== "false") return false;
  const limitMaximum = url.pathname.endsWith("/export") ? 2000 : 200;
  for (const [key, maximum] of [["limit", limitMaximum], ["offset", 100000]] as const) {
    const values = url.searchParams.getAll(key);
    if (values.length > 1) return false;
    if (values.length === 1) {
      const value = values[0];
      const minimum = key === "limit" ? 1 : 0;
      if (!value || !/^\d{1,7}$/.test(value) || Number(value) < minimum || Number(value) > maximum) return false;
    }
  }
  const afterValues = url.searchParams.getAll("after");
  if (afterValues.length === 1 && (!/^\d{1,16}$/.test(afterValues[0] ?? "") || Number(afterValues[0]) > Number.MAX_SAFE_INTEGER)) return false;
  return true;
}

function cookieValue(request: Request, name: string): string | undefined {
  const cookie = request.headers.get("cookie");
  if (!cookie) return undefined;
  for (const item of cookie.split(";")) {
    const separator = item.indexOf("=");
    if (separator < 0 || item.slice(0, separator).trim() !== name) continue;
    return item.slice(separator + 1).trim();
  }
  return undefined;
}

function accessToken(request: Request): string | undefined {
  return request.headers.get("cf-access-jwt-assertion") ?? cookieValue(request, "CF_Authorization");
}

async function verifyAdmin(request: Request, env: Env): Promise<{ token: string; claims: JWTPayload } | null> {
  const issuer = env.ACCESS_ISSUER.trim();
  const audience = env.ACCESS_AUDIENCE.trim();
  const allowedSubjects = new Set(env.ADMIN_SUBJECTS.split(",").map((subject) => subject.trim()).filter(Boolean));
  const token = accessToken(request);
  if (!issuer || !audience || allowedSubjects.size === 0 || !token) return null;

  let issuerUrl: URL;
  try {
    issuerUrl = new URL(issuer);
  } catch {
    return null;
  }
  if (issuerUrl.protocol !== "https:" || issuerUrl.username || issuerUrl.password || issuerUrl.pathname !== "/" || issuerUrl.search || issuerUrl.hash) return null;

  try {
    const jwks = createRemoteJWKSet(new URL("/cdn-cgi/access/certs", issuerUrl.origin));
    const verified = await jwtVerify(token, jwks, {
      issuer: issuerUrl.origin,
      audience,
      algorithms: ["RS256"],
      requiredClaims: ["exp", "iat", "sub"],
    });
    if (typeof verified.payload.sub !== "string" || !allowedSubjects.has(verified.payload.sub)) return null;
    return { token, claims: verified.payload };
  } catch {
    return null;
  }
}

function responseHeaders(upstream: Headers, isEventStream: boolean): Headers {
  const headers = new Headers();
  for (const name of FORWARDED_RESPONSE_HEADERS) {
    if (name === "cache-control") continue;
    const value = upstream.get(name);
    if (value !== null) headers.set(name, value);
  }
  if (isEventStream || upstream.get("content-type")?.toLowerCase().includes("text/event-stream")) {
    headers.set("content-type", "text/event-stream; charset=utf-8");
    headers.set("cache-control", "no-store, no-cache, no-transform");
    headers.set("x-accel-buffering", "no");
  }
  if (!isEventStream) headers.set("cache-control", "no-store");
  headers.set("x-content-type-options", "nosniff");
  return headers;
}

async function proxy(request: Request, url: URL, env: Env, verifiedAdminToken?: string): Promise<Response> {
  if (!env.ARENA_ORIGIN_TOKEN || !env.CF_ACCESS_CLIENT_ID || !env.CF_ACCESS_CLIENT_SECRET) {
    return json(503, "origin_unavailable");
  }

  const headers = new Headers();
  for (const name of FORWARDED_REQUEST_HEADERS) {
    const value = request.headers.get(name);
    if (value !== null) headers.set(name, value);
  }
  headers.set("x-arena-origin-token", env.ARENA_ORIGIN_TOKEN);
  headers.set("cf-access-client-id", env.CF_ACCESS_CLIENT_ID);
  headers.set("cf-access-client-secret", env.CF_ACCESS_CLIENT_SECRET);
  if (verifiedAdminToken) headers.set("x-arena-user-jwt", verifiedAdminToken);

  const target = new URL(url.pathname + url.search, ORIGIN);
  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: request.method,
      headers,
      redirect: "manual",
      body: request.method === "GET" || request.method === "HEAD" ? undefined : request.body,
    });
  } catch {
    return json(502, "origin_unavailable");
  }
  if (upstream.status >= 300 && upstream.status < 400) return json(502, "origin_unavailable");
  if (upstream.status >= 500) return json(502, "origin_unavailable");

  const isEventStream = url.pathname.endsWith("/stream");
  return new Response(upstream.body, {
    status: upstream.status,
    headers: responseHeaders(upstream.headers, isEventStream),
  });
}

async function checkRateLimit(env: Env, key: string): Promise<Response | null> {
  if (!env.ARENA_RATE_LIMITER) return json(503, "rate_limit_unavailable");
  try {
    const result = await env.ARENA_RATE_LIMITER.limit({ key });
    return result.success ? null : json(429, "rate_limit_exceeded");
  } catch {
    return json(503, "rate_limit_unavailable");
  }
}

function assetRequest(request: Request, pathname: string): Request {
  const url = new URL(request.url);
  url.pathname = pathname;
  return new Request(url, request);
}

function validAdminApi(method: string, pathname: string): boolean {
  if (method === "GET" || method === "HEAD") return ADMIN_READ_PATHS.some((pattern) => pattern.test(pathname));
  return method === "POST" && ADMIN_WRITE_PATHS.some((pattern) => pattern.test(pathname));
}

async function handle(request: Request, env: Env): Promise<Response> {
  const url = new URL(request.url);
  if (!safePath(url.pathname)) return json(404, "not_found");

  const isAdminPage = url.pathname === "/admin" || url.pathname.startsWith("/admin/");
  const isAdminAsset = url.pathname === "/admin-assets" || url.pathname.startsWith("/admin-assets/");
  const isAdminApi = url.pathname.startsWith("/api/v1/admin/");
  if (isAdminPage || isAdminAsset || isAdminApi) {
    if (isAdminApi && !validAdminApi(request.method, url.pathname)) return json(404, "not_found");
    if (!isAdminApi && request.method !== "GET" && request.method !== "HEAD") return json(405, "method_not_allowed");
    const verified = await verifyAdmin(request, env);
    if (!verified) return json(403, "admin_access_required");
    const rateLimit = await checkRateLimit(env, `admin:${verified.claims.sub}`);
    if (rateLimit) return rateLimit;
    if (isAdminApi) return proxy(request, url, env, verified.token);
    const assetPath = isAdminPage ? "/admin/" : url.pathname;
    return secureAsset(await env.ASSETS.fetch(assetRequest(request, assetPath)), true);
  }

  if (url.pathname.startsWith("/api/")) {
    if (!validPublicPath(url.pathname)) return json(404, "not_found");
    if (request.method !== "GET" && request.method !== "HEAD") return json(405, "method_not_allowed");
    if (!boundedQuery(url)) return json(400, "query_limit_exceeded");
    const client = request.headers.get("cf-connecting-ip") ?? "unknown-client";
    const rateLimit = await checkRateLimit(env, `public:${client}`);
    if (rateLimit) return rateLimit;
    return proxy(request, url, env);
  }

  if (url.pathname === "/simulation" || url.pathname.startsWith("/simulation/")) {
    return secureAsset(await env.ASSETS.fetch(assetRequest(request, "/")));
  }
  return secureAsset(await env.ASSETS.fetch(request));
}

function secureAsset(asset: Response, isPrivate = false): Response {
  const headers = new Headers(asset.headers);
  headers.set("content-security-policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'");
  headers.set("x-content-type-options", "nosniff");
  headers.set("referrer-policy", "strict-origin-when-cross-origin");
  headers.set("x-frame-options", "DENY");
  if (isPrivate) headers.set("cache-control", "no-store");
  return new Response(asset.body, { status: asset.status, statusText: asset.statusText, headers });
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    try {
      return await handle(request, env);
    } catch (error) {
      console.error(JSON.stringify({ event: "request_failed", error_type: error instanceof Error ? error.name : "unknown" }));
      return json(500, "internal_error");
    }
  },
} satisfies ExportedHandler<Env>;
