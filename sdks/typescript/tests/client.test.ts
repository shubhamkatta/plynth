import { describe, expect, it, vi } from "vitest";
import { MemoryStore, PlynthApiError, PlynthClient } from "../src/index.js";
import type { Tokens } from "../src/index.js";

const TOKENS: Tokens = {
  access_token: "a1",
  refresh_token: "r1",
  token_type: "bearer",
  expires_at: "2099-01-01T00:00:00Z",
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function mockFetch(handler: (url: string, init: RequestInit) => Promise<Response> | Response) {
  return vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
    const u = typeof url === "string" ? url : url.toString();
    return handler(u, init ?? {});
  });
}

describe("header construction", () => {
  it("sends X-Product-Slug and Bearer token on authed calls", async () => {
    const calls: { url: string; headers: Record<string, string> }[] = [];
    const fetchMock = mockFetch((url, init) => {
      calls.push({ url, headers: Object.fromEntries(new Headers(init.headers).entries()) });
      return jsonResponse([{ id: "1" }]);
    });
    const store = new MemoryStore();
    store.set(TOKENS);
    const c = new PlynthClient({
      baseUrl: "https://api.test",
      productSlug: "chatbot",
      tokenStore: store,
      fetch: fetchMock as unknown as typeof fetch,
    });

    await c.tenants.list();
    expect(calls[0]?.url).toBe("https://api.test/api/v1/tenants");
    expect(calls[0]?.headers["x-product-slug"]).toBe("chatbot");
    expect(calls[0]?.headers["authorization"]).toBe("Bearer a1");
  });

  it("routes admin paths through X-Platform-Admin-Token", async () => {
    const calls: Record<string, string>[] = [];
    const fetchMock = mockFetch((_url, init) => {
      calls.push(Object.fromEntries(new Headers(init.headers).entries()));
      return jsonResponse([]);
    });
    const c = new PlynthClient({
      baseUrl: "https://api.test",
      adminToken: "admin-secret",
      fetch: fetchMock as unknown as typeof fetch,
    });

    await c.products.list();
    expect(calls[0]?.["x-platform-admin-token"]).toBe("admin-secret");
    expect(calls[0]?.["authorization"]).toBeUndefined();
  });

  it("auto-generates Idempotency-Key on mutating calls", async () => {
    const calls: Record<string, string>[] = [];
    const fetchMock = mockFetch((_url, init) => {
      calls.push(Object.fromEntries(new Headers(init.headers).entries()));
      return jsonResponse({});
    });
    const store = new MemoryStore();
    store.set(TOKENS);
    const c = new PlynthClient({
      baseUrl: "https://api.test",
      productSlug: "p",
      tokenStore: store,
      fetch: fetchMock as unknown as typeof fetch,
    });
    await c.credits.consume({ feature_key: "x", amount: "1" });
    expect(calls[0]?.["idempotency-key"]).toMatch(/^[0-9a-f-]{36}$/i);
  });

  it("sends X-Acting-Tenant-Slug when configured", async () => {
    const calls: Record<string, string>[] = [];
    const fetchMock = mockFetch((_url, init) => {
      calls.push(Object.fromEntries(new Headers(init.headers).entries()));
      return jsonResponse([]);
    });
    const store = new MemoryStore();
    store.set(TOKENS);
    const c = new PlynthClient({
      baseUrl: "https://api.test",
      productSlug: "p",
      actingTenantSlug: "child",
      tokenStore: store,
      fetch: fetchMock as unknown as typeof fetch,
    });
    await c.tenants.list();
    expect(calls[0]?.["x-acting-tenant-slug"]).toBe("child");
  });
});

describe("refresh-once on 401", () => {
  it("refreshes and retries on 401, persisting new tokens", async () => {
    let n = 0;
    const fetchMock = mockFetch((url) => {
      n += 1;
      if (url.endsWith("/api/v1/auth/me") && n === 1) return new Response("", { status: 401 });
      if (url.endsWith("/api/v1/auth/refresh"))
        return jsonResponse({
          access_token: "a2",
          refresh_token: "r2",
          token_type: "bearer",
          expires_at: "2099-01-01T00:00:00Z",
        });
      if (url.endsWith("/api/v1/auth/me"))
        return jsonResponse({ id: "u", email: "x@x", permissions: [] });
      return new Response("", { status: 500 });
    });
    const store = new MemoryStore();
    store.set(TOKENS);
    const c = new PlynthClient({
      baseUrl: "https://api.test",
      productSlug: "p",
      tokenStore: store,
      fetch: fetchMock as unknown as typeof fetch,
    });
    const me = await c.auth.me();
    expect(me.email).toBe("x@x");
    expect(store.get()?.access_token).toBe("a2");
    expect(n).toBe(3);
  });

  it("clears store and throws when refresh fails", async () => {
    const fetchMock = mockFetch((url) => {
      if (url.endsWith("/auth/refresh")) return new Response("", { status: 401 });
      return new Response(JSON.stringify({ code: "unauthorized", message: "x" }), {
        status: 401,
        headers: { "Content-Type": "application/json" },
      });
    });
    const store = new MemoryStore();
    store.set(TOKENS);
    const c = new PlynthClient({
      baseUrl: "https://api.test",
      productSlug: "p",
      tokenStore: store,
      fetch: fetchMock as unknown as typeof fetch,
    });
    await expect(c.auth.me()).rejects.toBeInstanceOf(PlynthApiError);
    expect(store.get()).toBeNull();
  });
});

describe("error envelope", () => {
  it("parses {code,message,details} into PlynthApiError", async () => {
    const fetchMock = mockFetch(() =>
      new Response(
        JSON.stringify({ code: "insufficient_credits", message: "not enough", details: { need: 5 } }),
        { status: 402, headers: { "Content-Type": "application/json" } },
      ),
    );
    const store = new MemoryStore();
    store.set(TOKENS);
    const c = new PlynthClient({
      baseUrl: "https://api.test",
      productSlug: "p",
      tokenStore: store,
      fetch: fetchMock as unknown as typeof fetch,
    });
    try {
      await c.credits.consume({ feature_key: "x", amount: "1" });
      throw new Error("should have thrown");
    } catch (err) {
      expect(err).toBeInstanceOf(PlynthApiError);
      const e = err as PlynthApiError;
      expect(e.status).toBe(402);
      expect(e.code).toBe("insufficient_credits");
      expect(e.details["need"]).toBe(5);
    }
  });
});
