// Runtime proxy for the /v1/self-test/* endpoints. We replaced the
// next.config rewrite version because rewrite destinations are baked at
// `next build` time — in container deployments where BACKEND_URL is
// set at runtime, the rewrite ended up pointing at the build-time
// default (`http://localhost:8000`) and 502'd with ECONNREFUSED.
// Route handlers read process.env on every request so they always see
// the live env value.

import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";
const TIMEOUT_MS = 10_000;

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

async function relay(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
): Promise<Response> {
  const { path } = await context.params;
  const upstreamPath = path.join("/");
  const url = `${BACKEND_URL}/v1/self-test/${upstreamPath}`;

  let upstream: Response;
  try {
    upstream = await fetch(url, {
      method: request.method,
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : "upstream failed";
    return NextResponse.json(
      { error: `backend unreachable: ${message}` },
      { status: 502 },
    );
  }

  // Pass through body, status, and the headers judges care about
  // (Content-Type for in-place rendering, Content-Disposition so the
  // browser uses the right download filename).
  const headers: Record<string, string> = {};
  const ct = upstream.headers.get("content-type");
  if (ct) headers["content-type"] = ct;
  const cd = upstream.headers.get("content-disposition");
  if (cd) headers["content-disposition"] = cd;
  headers["cache-control"] = "no-store";

  return new Response(upstream.body, {
    status: upstream.status,
    headers,
  });
}

export const GET = relay;
