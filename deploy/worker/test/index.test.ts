import { exportJWK, generateKeyPair, SignJWT } from "jose";
import { afterEach, describe, expect, it, vi } from "vitest";
import worker from "../src/index";

const apiOrigin = "https://arena-origin.leonfuller.com";

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

  it("rewrites simulation routes to the landing entry and sends a restrictive CSP", async () => {
    const fetchAsset = vi.fn(async (request: Request) => new Response(new URL(request.url).pathname));
    const env = makeEnv({ ASSETS: { ...makeEnv().ASSETS, fetch: fetchAsset } });
    const response = await worker.fetch(new Request("https://arena.test/simulation/competition/c1"), env);

    expect(await response.text()).toBe("/index.html");
    expect(response.headers.get("content-security-policy")).toContain("script-src 'self'");
    expect(response.headers.get("content-security-policy")).toContain("style-src 'self' 'unsafe-inline'");
    expect(response.headers.get("x-frame-options")).toBe("DENY");
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
    const issuer = "https://tenant.cloudflareaccess.com";
    const audience = "admin-audience";
    const { publicKey, privateKey } = await generateKeyPair("RS256");
    const jwk = await exportJWK(publicKey);
    jwk.kid = "edge-test-key";
    jwk.alg = "RS256";
    jwk.use = "sig";
    const token = await new SignJWT({})
      .setProtectedHeader({ alg: "RS256", kid: jwk.kid })
      .setIssuer(issuer)
      .setAudience(audience)
      .setSubject("admin-user-1")
      .setIssuedAt()
      .setExpirationTime("5m")
      .sign(privateKey);
    const unauthorizedToken = await new SignJWT({})
      .setProtectedHeader({ alg: "RS256", kid: jwk.kid })
      .setIssuer(issuer)
      .setAudience(audience)
      .setSubject("visitor-user-2")
      .setIssuedAt()
      .setExpirationTime("5m")
      .sign(privateKey);

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
    const request = new Request("https://arena.test/api/v1/admin/status", {
      headers: {
        "cf-access-jwt-assertion": token,
        "x-arena-user-jwt": "forged-backend-token",
        origin: "https://arena.test",
      },
    });
    const unauthorized = await worker.fetch(new Request("https://arena.test/api/v1/admin/status", {
      headers: { "cf-access-jwt-assertion": unauthorizedToken },
    }), env);
    expect(unauthorized.status).toBe(403);
    expect(originFetch).not.toHaveBeenCalled();

    const response = await worker.fetch(request, env);

    expect(response.status).toBe(200);
    const forwarded = new Headers(originFetch.mock.calls[0]?.[1]?.headers);
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
