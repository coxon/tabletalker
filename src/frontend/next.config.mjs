/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Backend URL is read at request time from process.env.BACKEND_URL,
  // defaulting to http://localhost:8000 (see app/page.tsx, app/api/health/route.ts).
};

export default nextConfig;
