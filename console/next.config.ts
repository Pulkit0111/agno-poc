import path from "path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  turbopack: {
    // Pin the workspace root to this app — a stray lockfile elsewhere on the
    // machine (e.g. the user's home directory) can otherwise make Turbopack
    // infer the wrong root.
    root: path.resolve(__dirname),
  },
  async rewrites() {
    // Dev only: same-origin /api/* proxied to FastAPI. In prod both sit
    // behind one tunnel/reverse-proxy, so this rewrite is a no-op there.
    // BOTT_API_ORIGIN overrides the target — the backend's own default port
    // is 7777 (src/bott/interfaces/app.py), configurable via BOTT_PORT.
    const apiOrigin = process.env.BOTT_API_ORIGIN ?? "http://localhost:7777";
    return [{ source: "/api/:path*", destination: `${apiOrigin}/api/:path*` }];
  },
};

export default nextConfig;
