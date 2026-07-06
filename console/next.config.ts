import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async rewrites() {
    // Dev only: same-origin /api/* proxied to FastAPI. In prod both sit
    // behind one tunnel/reverse-proxy, so this rewrite is a no-op there.
    return [{ source: "/api/:path*", destination: "http://localhost:8000/api/:path*" }];
  },
};

export default nextConfig;
