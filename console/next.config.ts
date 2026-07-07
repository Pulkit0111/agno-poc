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
    // Load-bearing in production, not just dev: the single cloudflared tunnel
    // points at the console (port 3000), and everything destined for the
    // Python API arrives through this origin — the console API (/api/*),
    // Slack Events/interactivity (/slack/*), and the GitHub webhook
    // (/webhook/*). These rewrites proxy the raw request through unchanged
    // (Slack signature verification happens on the raw body server-side, so
    // no body handling belongs here).
    // BOTT_API_ORIGIN overrides the target — the backend's own default port
    // is 7777 (src/bott/interfaces/app.py), configurable via BOTT_PORT.
    const apiOrigin = process.env.BOTT_API_ORIGIN ?? "http://localhost:7777";
    return [
      { source: "/api/:path*", destination: `${apiOrigin}/api/:path*` },
      { source: "/slack/:path*", destination: `${apiOrigin}/slack/:path*` },
      { source: "/webhook/:path*", destination: `${apiOrigin}/webhook/:path*` },
    ];
  },
};

export default nextConfig;
