import type { NextConfig } from "next";

// In the shared docker-compose network the API is reachable at the service
// name "api". For local `pnpm dev` iteration outside Docker, override with
// API_INTERNAL_URL (e.g. http://127.0.0.1:8100 via a temporary proxy).
const apiOrigin = process.env.API_INTERNAL_URL ?? "http://api:8000";

const nextConfig: NextConfig = {
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${apiOrigin}/api/:path*` }];
  },
};

export default nextConfig;
