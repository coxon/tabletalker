/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Hide the Next.js dev indicator — the corner badge clashes with the
  // editorial register and adds nothing for our single-screen app.
  devIndicators: false,
  // Backend URL is read at request time from process.env.BACKEND_URL,
  // defaulting to http://localhost:8000 (see app/page.tsx, app/api/health/route.ts).
};

export default nextConfig;
