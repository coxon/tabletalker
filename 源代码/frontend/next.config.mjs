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
      // /api/self-test/* used to be a rewrite here, but rewrite
      // destinations are baked at `next build` time — in containers
      // where BACKEND_URL is set at runtime (not at build), the rewrite
      // ends up pointing at `http://localhost:8000` and fails with
      // ECONNREFUSED. Replaced by a runtime route handler at
      // `app/api/self-test/[...path]/route.ts` which reads BACKEND_URL
      // on each request — same pattern as /api/analyze.
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
