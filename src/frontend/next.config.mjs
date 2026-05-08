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
        source: "/reports/:path*",
        destination: `${BACKEND_URL}/reports/:path*`,
      },
    ];
  },
};

export default nextConfig;
