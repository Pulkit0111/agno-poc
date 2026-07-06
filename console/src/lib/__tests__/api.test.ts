import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError } from "../api";

afterEach(() => vi.unstubAllGlobals());

describe("api", () => {
  it("returns parsed json", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ ok: 1 }))));
    expect(await api<{ ok: number }>("/api/console/v1/me")).toEqual({ ok: 1 });
  });

  it("throws ApiError with envelope code and message", async () => {
    const body = JSON.stringify({ detail: { error: { code: "admin_only", message: "This needs an admin." } } });
    vi.stubGlobal("fetch", vi.fn(async () => new Response(body, { status: 403 })));
    const err = (await api("/x").catch((e) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.code).toBe("admin_only");
    expect(err.message).toBe("This needs an admin.");
  });
});
