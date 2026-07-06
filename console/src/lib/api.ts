export class ApiError extends Error {
  code: string;
  status: number;
  constructor(status: number, code: string, message: string) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (res.ok) return res.json() as Promise<T>;
  if (res.status === 401 && typeof window !== "undefined") {
    try { await fetch("/api/console/auth/logout", { method: "POST" }); } catch { /* best effort */ }
    window.location.href = "/login";
  }
  let code = "unknown";
  let message = "Something went wrong on the server.";
  try {
    const body = await res.json();
    code = body?.detail?.error?.code ?? code;
    message = body?.detail?.error?.message ?? message;
  } catch {
    /* non-JSON error body — keep defaults */
  }
  throw new ApiError(res.status, code, message);
}
