// Streaming variant of /api/follow-up: passes the JSON body through to
// the backend's /v1/follow-up/stream and relays the NDJSON
// ReadableStream directly to the browser. Mirrors
// /api/analyze/stream/route.ts; see that file for buffering caveats and
// for why no `AbortSignal.timeout` is set on the upstream fetch (the
// backend owns stream-termination semantics).

import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(request: NextRequest): Promise<Response> {
  let payload: string;
  try {
    payload = await request.text();
  } catch {
    return NextResponse.json(
      { error: "invalid json payload" },
      { status: 400 },
    );
  }

  let upstream: Response;
  try {
    upstream = await fetch(`${BACKEND_URL}/v1/follow-up/stream`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: payload,
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : "upstream failed";
    return NextResponse.json(
      { error: `backend unreachable: ${message}` },
      { status: 502 },
    );
  }

  return new Response(upstream.body, {
    status: upstream.status,
    headers: {
      "content-type":
        upstream.headers.get("content-type") ?? "application/x-ndjson",
      "cache-control": "no-store",
      "x-accel-buffering": "no",
    },
  });
}
