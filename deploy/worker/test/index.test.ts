import { exportJWK, generateKeyPair, SignJWT } from "jose";
import { afterEach, describe, expect, it, vi } from "vitest";
import worker from "../src/index";

const apiOrigin = "https://arena-origin.leonfuller.com";
const accessIssuer = "https://tenant.cloudflareaccess.com";
const accessAudience = "admin-audience";

function makeEnv(overrides: Partial<Env> = {}): Env {
  return {
    ASSETS: {
      fetch: vi.fn(async () => new Response("static", { status: 200 })),
      connect: () => { throw new Error("asset fixture has no sockets"); },
    },
    ACCESS_ISSUER: "",
    ACCESS_AUDIENCE: "",
    ADMIN_SUBJECTS: "",
    ARENA_ORIGIN_TOKEN: "origin-secret",
    CF_ACCESS_CLIENT_ID: "service-id",
    CF_ACCESS_CLIENT_SECRET: "service-secret",
    ARENA_RATE_LIMITER: { limit: vi.fn(async () => ({ success: true })) },
    ...overrides,
  };
}

async function signedAccessToken(
  privateKey: CryptoKey,
  kid: string,
  overrides: {
    issuer?: string;
    audience?: string;
    subject?: string | null;
    issuedAt?: boolean;
    expiresAt?: string | null;
  } = {},
): Promise<string> {
  let token = new SignJWT({}).setProtectedHeader({ alg: "RS256", kid });
  token = token.setIssuer(overrides.issuer ?? accessIssuer).setAudience(overrides.audience ?? accessAudience);
  if (overrides.subject !== null) token = token.setSubject(overrides.subject ?? "admin-user-1");
  if (overrides.issuedAt !== false) token = token.setIssuedAt();
  if (overrides.expiresAt !== null) token = token.setExpirationTime(overrides.expiresAt ?? "5m");
  return token.sign(privateKey);
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("edge request boundaries", () => {
  it("rejects unknown API paths and public writes before calling the origin", async () => {
    const fetchMock = vi.fn(async () => new Response("ok", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const env = makeEnv();

    const unknown = await worker.fetch(new Request("https://arena.test/api/v1/public/private"), env);
    const write = await worker.fetch(new Request("https://arena.test/api/v1/public/status", { method: "POST" }), env);

    expect(unknown.status).toBe(404);
    expect(write.status).toBe(405);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects unbounded public query parameters", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const response = await worker.fetch(
      new Request("https://arena.test/api/v1/public/competitions?limit=201"),
      makeEnv(),
    );

    expect(response.status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("allows offset zero while requiring limit to be positive", async () => {
    const fetchMock = vi.fn(async () => new Response("ok", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const env = makeEnv();
    const firstPage = await worker.fetch(
      new Request("https://arena.test/api/v1/public/competitions?limit=1&offset=0"),
      env,
    );
    const invalidLimit = await worker.fetch(
      new Request("https://arena.test/api/v1/public/competitions?limit=0&offset=0"),
      env,
    );

    expect(firstPage.status).toBe(200);
    expect(invalidLimit.status).toBe(400);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("forwards bounded public funding history and exact evidence routes", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => new Response(String(input), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const env = makeEnv();
    const funding = await worker.fetch(
      new Request("https://arena.test/api/v1/public/competitions/c1/funding?limit=50&offset=20&agent_id=agent-1&symbol=BTC"),
      env,
    );
    const evidence = await worker.fetch(
      new Request("https://arena.test/api/v1/public/funding/evidence/evidence-1"),
      env,
    );
    const tooManyRows = await worker.fetch(
      new Request("https://arena.test/api/v1/public/competitions/c1/funding?limit=201"),
      env,
    );
    const unknownFilter = await worker.fetch(
      new Request("https://arena.test/api/v1/public/competitions/c1/funding?all=true"),
      env,
    );
    const wrongMethod = await worker.fetch(
      new Request("https://arena.test/api/v1/public/funding/evidence/evidence-1", { method: "POST" }),
      env,
    );
    const unlisted = await worker.fetch(
      new Request("https://arena.test/api/v1/public/funding/evidence/evidence-1/raw"),
      env,
    );

    expect(funding.status).toBe(200);
    expect(evidence.status).toBe(200);
    expect(tooManyRows.status).toBe(400);
    expect(unknownFilter.status).toBe(400);
    expect(wrongMethod.status).toBe(405);
    expect(unlisted.status).toBe(404);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(String(fetchMock.mock.calls[0]?.[0])).toBe(`${apiOrigin}/api/v1/public/competitions/c1/funding?limit=50&offset=20&agent_id=agent-1&symbol=BTC`);
    expect(String(fetchMock.mock.calls[1]?.[0])).toBe(`${apiOrigin}/api/v1/public/funding/evidence/evidence-1`);
  });

  it("allows only the competition's frozen-rules artifact route", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => new Response(String(input), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const env = makeEnv();
    const rules = await worker.fetch(
      new Request("https://arena.test/api/v1/public/competitions/c1/rules"),
      env,
    );
    const wrongMethod = await worker.fetch(
      new Request("https://arena.test/api/v1/public/competitions/c1/rules", { method: "POST" }),
      env,
    );
    const unlisted = await worker.fetch(
      new Request("https://arena.test/api/v1/public/competitions/c1/rules/raw"),
      env,
    );

    expect(rules.status).toBe(200);
    expect(wrongMethod.status).toBe(405);
    expect(unlisted.status).toBe(404);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(String(fetchMock.mock.calls[0]?.[0])).toBe(`${apiOrigin}/api/v1/public/competitions/c1/rules`);
  });

  it("allows competition metrics and validates the optional ticker competition UUID", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => new Response(String(input), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const env = makeEnv();
    const metrics = await worker.fetch(
      new Request("https://arena.test/api/v1/public/competitions/c1/metrics"),
      env,
    );
    const scopedTicker = await worker.fetch(
      new Request("https://arena.test/api/v1/public/ticker?competition_id=2d5cb149-9597-4ae2-88cb-7a37e28a8841"),
      env,
    );
    const invalidTicker = await worker.fetch(
      new Request("https://arena.test/api/v1/public/ticker?competition_id=not-a-uuid"),
      env,
    );
    const repeatedTicker = await worker.fetch(
      new Request("https://arena.test/api/v1/public/ticker?competition_id=2d5cb149-9597-4ae2-88cb-7a37e28a8841&competition_id=2d5cb149-9597-4ae2-88cb-7a37e28a8841"),
      env,
    );

    expect(metrics.status).toBe(200);
    expect(scopedTicker.status).toBe(200);
    expect(invalidTicker.status).toBe(400);
    expect(repeatedTicker.status).toBe(400);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(String(fetchMock.mock.calls[1]?.[0])).toBe(`${apiOrigin}/api/v1/public/ticker?competition_id=2d5cb149-9597-4ae2-88cb-7a37e28a8841`);
  });

  it("forwards chart ranges and enforces the requested sampling bounds", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => new Response(String(input), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const env = makeEnv();
    const accepted = await worker.fetch(
      new Request("https://arena.test/api/v1/public/competitions/c1/chart?range=72H&points=400"),
      env,
    );
    const invalidRange = await worker.fetch(
      new Request("https://arena.test/api/v1/public/competitions/c1/chart?range=7D"),
      env,
    );
    const tooFewPoints = await worker.fetch(
      new Request("https://arena.test/api/v1/public/competitions/c1/chart?points=1"),
      env,
    );
    const tooManyPoints = await worker.fetch(
      new Request("https://arena.test/api/v1/public/competitions/c1/chart?points=401"),
      env,
    );
    const duplicateRange = await worker.fetch(
      new Request("https://arena.test/api/v1/public/competitions/c1/chart?range=ALL&range=24H"),
      env,
    );

    expect(accepted.status).toBe(200);
    expect(invalidRange.status).toBe(400);
    expect(tooFewPoints.status).toBe(400);
    expect(tooManyPoints.status).toBe(400);
    expect(duplicateRange.status).toBe(400);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(String(fetchMock.mock.calls[0]?.[0])).toBe(`${apiOrigin}/api/v1/public/competitions/c1/chart?range=72H&points=400`);
  });

  it("keeps new admin writes behind Access and rejects wrong verbs or paths", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const env = makeEnv();
    const writes = [
      new Request("https://arena.test/api/v1/admin/competitions", { method: "POST", body: "{}" }),
      new Request("https://arena.test/api/v1/admin/providers", { method: "POST", body: "{}" }),
      new Request("https://arena.test/api/v1/admin/prompts", { method: "POST", body: "{}" }),
      new Request("https://arena.test/api/v1/admin/providers/2d5cb149-9597-4ae2-88cb-7a37e28a8841/test", { method: "POST" }),
    ];
    const anonymous = await Promise.all(writes.map((request) => worker.fetch(request, env)));
    const wrongVerb = await worker.fetch(new Request("https://arena.test/api/v1/admin/providers/2d5cb149-9597-4ae2-88cb-7a37e28a8841/test"), env);
    const unknown = await worker.fetch(new Request("https://arena.test/api/v1/admin/providers/validate", { method: "POST" }), env);

    expect(anonymous.map((response) => response.status)).toEqual([403, 403, 403, 403]);
    expect(wrongVerb.status).toBe(404);
    expect(unknown.status).toBe(404);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("permits export limits through 2000 and requires a real rate-limit binding", async () => {
    const fetchMock = vi.fn(async () => new Response("ok", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const env = makeEnv();
    const accepted = await worker.fetch(
      new Request("https://arena.test/api/v1/public/competitions/c1/export?limit=2000"),
      env,
    );
    const denied = await worker.fetch(
      new Request("https://arena.test/api/v1/public/competitions/c1/export?limit=2001"),
      env,
    );
    const missingBinding = await worker.fetch(
      new Request("https://arena.test/api/v1/public/status"),
      makeEnv({ ARENA_RATE_LIMITER: undefined }),
    );
    const limited = await worker.fetch(
      new Request("https://arena.test/api/v1/public/status"),
      makeEnv({ ARENA_RATE_LIMITER: { limit: vi.fn(async () => ({ success: false })) } }),
    );

    expect(accepted.status).toBe(200);
    expect(denied.status).toBe(400);
    expect(missingBinding.status).toBe(503);
    expect(limited.status).toBe(429);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("rewrites simulation routes to the canonical landing path and sends a restrictive CSP", async () => {
    const fetchAsset = vi.fn(async (request: Request) => new Response(new URL(request.url).pathname));
    const env = makeEnv({ ASSETS: { ...makeEnv().ASSETS, fetch: fetchAsset } });
    const response = await worker.fetch(new Request("https://arena.test/simulation/competition/c1"), env);
    const exactRoute = await worker.fetch(new Request("https://arena.test/simulation"), env);

    expect(await response.text()).toBe("/");
    expect(await exactRoute.text()).toBe("/");
    expect(fetchAsset.mock.calls.map(([request]) => new URL(request.url).pathname)).toEqual(["/", "/"]);
    expect(response.headers.get("content-security-policy")).toContain("script-src 'self'");
    expect(response.headers.get("content-security-policy")).toContain("style-src 'self' 'unsafe-inline'");
    expect(response.headers.get("x-frame-options")).toBe("DENY");
  });

  it("rewrites authorized admin pages to the canonical protected directory", async () => {
    const { publicKey, privateKey } = await generateKeyPair("RS256");
    const jwk = await exportJWK(publicKey);
    jwk.kid = "edge-admin-page-key";
    jwk.alg = "RS256";
    jwk.use = "sig";
    const token = await signedAccessToken(privateKey, String(jwk.kid));
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = input instanceof Request ? input.url : String(input);
      return url === `${accessIssuer}/cdn-cgi/access/certs`
        ? Response.json({ keys: [jwk] })
        : new Response("unexpected outbound request", { status: 500 });
    }));
    const fetchAsset = vi.fn(async (request: Request) => new Response(new URL(request.url).pathname));
    const env = makeEnv({
      ASSETS: { ...makeEnv().ASSETS, fetch: fetchAsset },
      ACCESS_ISSUER: accessIssuer,
      ACCESS_AUDIENCE: accessAudience,
      ADMIN_SUBJECTS: "admin-user-1",
    });
    const response = await worker.fetch(new Request("https://arena.test/admin/competitions", {
      headers: { "cf-access-jwt-assertion": token },
    }), env);

    expect(response.status).toBe(200);
    expect(await response.text()).toBe("/admin/");
    expect(fetchAsset).toHaveBeenCalledTimes(1);
  });

  it("keeps admin entry routes behind Access and rejects unlisted admin APIs", async () => {
    const env = makeEnv();
    const page = await worker.fetch(new Request("https://arena.test/admin/competitions"), env);
    const unknown = await worker.fetch(new Request("https://arena.test/api/v1/admin/secrets"), env);

    expect(page.status).toBe(403);
    expect(unknown.status).toBe(404);
    expect(env.ASSETS.fetch).not.toHaveBeenCalled();
  });

  it("uses the fixed origin and removes forged visitor credentials on public reads", async () => {
    let capturedUrl = "";
    let capturedHeaders = new Headers();
    const limiter = vi.fn(async () => ({ success: true }));
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      capturedUrl = String(input);
      capturedHeaders = new Headers(init?.headers);
      return new Response('{"items":[]}', { status: 200, headers: { "content-type": "application/json" } });
    }));
    const request = new Request("https://arena.test/api/v1/public/competitions?limit=25", {
      headers: {
        authorization: "Bearer visitor-forgery",
        cookie: "session=visitor-forgery",
        "x-arena-origin-token": "forged-origin-token",
        "x-arena-user-jwt": "forged-user-jwt",
        "cf-access-client-id": "forged-client",
        "cf-access-client-secret": "forged-secret",
        "cf-access-jwt-assertion": "forged-assertion",
        "cf-connecting-ip": "203.0.113.8",
        accept: "application/json",
      },
    });

    const env = makeEnv({ ARENA_RATE_LIMITER: { limit: limiter } });
    const response = await worker.fetch(request, env);

    expect(response.status).toBe(200);
    expect(capturedUrl).toBe(`${apiOrigin}/api/v1/public/competitions?limit=25`);
    expect(capturedHeaders.get("x-arena-origin-token")).toBe("origin-secret");
    expect(capturedHeaders.get("cf-access-client-id")).toBe("service-id");
    expect(capturedHeaders.get("cf-access-client-secret")).toBe("service-secret");
    expect(capturedHeaders.has("x-arena-user-jwt")).toBe(false);
    expect(capturedHeaders.has("cf-access-jwt-assertion")).toBe(false);
    expect(capturedHeaders.has("authorization")).toBe(false);
    expect(capturedHeaders.has("cookie")).toBe(false);
    expect(limiter).toHaveBeenCalledWith({ key: "public:203.0.113.8" });
  });

  it("fails closed for admin pages and APIs when Access configuration is missing", async () => {
    const env = makeEnv();
    const page = await worker.fetch(new Request("https://arena.test/admin"), env);
    const api = await worker.fetch(new Request("https://arena.test/api/v1/admin/status"), env);

    expect(page.status).toBe(403);
    expect(api.status).toBe(403);
    expect(env.ASSETS.fetch).not.toHaveBeenCalled();
  });

  it("forwards only the verified admin JWT in the dedicated backend header", async () => {
    const issuer = accessIssuer;
    const audience = accessAudience;
    const { publicKey, privateKey } = await generateKeyPair("RS256");
    const jwk = await exportJWK(publicKey);
    jwk.kid = "edge-test-key";
    jwk.alg = "RS256";
    jwk.use = "sig";
    const token = await signedAccessToken(privateKey, String(jwk.kid));
    const invalidKeyPair = await generateKeyPair("RS256");
    const invalidTokens = await Promise.all([
      signedAccessToken(privateKey, String(jwk.kid), { audience: "wrong-audience" }),
      signedAccessToken(privateKey, String(jwk.kid), { issuer: "https://wrong.cloudflareaccess.com" }),
      signedAccessToken(privateKey, String(jwk.kid), { expiresAt: null }),
      signedAccessToken(privateKey, String(jwk.kid), { issuedAt: false }),
      signedAccessToken(privateKey, String(jwk.kid), { subject: null }),
      signedAccessToken(privateKey, String(jwk.kid), { expiresAt: "-10s" }),
      signedAccessToken(invalidKeyPair.privateKey, String(jwk.kid)),
      signedAccessToken(privateKey, String(jwk.kid), { subject: "visitor-user-2" }),
    ]);

    const originFetch = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => new Response('{"ok":true}', { status: 200, headers: { "content-type": "application/json" } }));
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const requestedUrl = input instanceof Request ? input.url : String(input);
      if (requestedUrl === `${issuer}/cdn-cgi/access/certs`) {
        return Response.json({ keys: [jwk] });
      }
      return originFetch(input, init);
    }));
    const adminLimiter = vi.fn(async () => ({ success: true }));
    const env = makeEnv({
      ACCESS_ISSUER: issuer,
      ACCESS_AUDIENCE: audience,
      ADMIN_SUBJECTS: "admin-user-1",
      ARENA_RATE_LIMITER: { limit: adminLimiter },
    });
    const request = new Request("https://arena.test/api/v1/admin/providers", {
      method: "POST",
      headers: {
        "cf-access-jwt-assertion": token,
        "x-arena-user-jwt": "forged-backend-token",
        origin: "https://arena.test",
        "content-type": "application/json",
      },
      body: JSON.stringify({ name: "reviewed-profile", api_key_env: "TEST_KEY" }),
    });
    const denied = await Promise.all(invalidTokens.map((invalidToken) => worker.fetch(
      new Request("https://arena.test/api/v1/admin/providers", {
        method: "POST",
        headers: { "cf-access-jwt-assertion": invalidToken, "content-type": "application/json" },
        body: "{}",
      }),
      env,
    )));
    expect(denied.map((response) => response.status)).toEqual(Array(invalidTokens.length).fill(403));
    expect(originFetch).not.toHaveBeenCalled();
    expect(env.ASSETS.fetch).not.toHaveBeenCalled();

    const response = await worker.fetch(request, env);

    expect(response.status).toBe(200);
    const forwarded = new Headers(originFetch.mock.calls[0]?.[1]?.headers);
    expect(String(fetchMockCallUrl(originFetch.mock.calls[0]?.[0]))).toBe(`${apiOrigin}/api/v1/admin/providers`);
    expect(originFetch.mock.calls[0]?.[1]?.method).toBe("POST");
    expect(originFetch.mock.calls[0]?.[1]?.body).toBeTruthy();
    expect(forwarded.get("content-type")).toBe("application/json");
    expect(forwarded.get("x-arena-user-jwt")).toBe(token);
    expect(forwarded.get("x-arena-origin-token")).toBe("origin-secret");
    expect(forwarded.get("origin")).toBe("https://arena.test");
    expect(forwarded.get("cf-access-jwt-assertion")).toBe(null);
    expect(adminLimiter).toHaveBeenCalledWith({ key: "admin:admin-user-1" });
  });

  it("streams event responses and suppresses redirects and raw upstream failures", async () => {
    const source = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new TextEncoder().encode("data: one\n\n"));
        controller.close();
      },
    });
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(source, { status: 200, headers: { "content-type": "text/event-stream" } }))
      .mockResolvedValueOnce(new Response("https://attacker.test", { status: 302, headers: { location: "https://attacker.test" } }))
      .mockResolvedValueOnce(new Response("database password leaked", { status: 500 }));
    vi.stubGlobal("fetch", fetchMock);
    const env = makeEnv();

    const stream = await worker.fetch(new Request("https://arena.test/api/v1/public/competitions/c1/stream"), env);
    const redirect = await worker.fetch(new Request("https://arena.test/api/v1/public/status"), env);
    const failure = await worker.fetch(new Request("https://arena.test/api/v1/public/status"), env);

    expect(stream.headers.get("content-type")).toContain("text/event-stream");
    expect(stream.headers.get("cache-control")).toContain("no-cache");
    expect(stream.body).toBe(source);
    expect(await stream.text()).toBe("data: one\n\n");
    expect(redirect.status).toBe(502);
    expect(await redirect.json()).toEqual({ error: "origin_unavailable" });
    expect(failure.status).toBe(502);
    expect(await failure.text()).not.toContain("database password leaked");
  });
});

function fetchMockCallUrl(input: RequestInfo | URL | undefined): string {
  if (input instanceof Request) return input.url;
  return input === undefined ? "" : String(input);
}
