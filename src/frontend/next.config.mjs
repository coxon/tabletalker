const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  devIndicators: false,
  async rewrites() {
    return [
      {
        source: "/api/batch",
        destination: `${BACKEND_URL}/v1/batch`,
      },
      {
        // History page (`/history`) and reports list (`/reports`) hit
        // `/api/sessions` and `/api/sessions/{id}`; without this rewrite
        // those land in Next.js as 404, which renders as a "无法加载历史"
        // empty state on those pages.
        source: "/api/sessions/:path*",
        destination: `${BACKEND_URL}/v1/sessions/:path*`,
      },
      {
        source: "/api/sessions",
        destination: `${BACKEND_URL}/v1/sessions`,
      },
      {
        source: "/reports/:path*",
        destination: `${BACKEND_URL}/reports/:path*`,
      },
    ];
  },
  async redirects() {
    // The new UI replaced the old `(shell)` shell at the root path. Anyone
    // who bookmarked or shared a `/v2/*` link from the previous layout
    // (e.g. README, demo videos, eval scripts) gets a 308 to the canonical
    // root path so the new content is what they see.
    return [
      { source: "/v2", destination: "/", permanent: true },
      { source: "/v2/:path*", destination: "/:path*", permanent: true },
    ];
  },
};

export default nextConfig;
