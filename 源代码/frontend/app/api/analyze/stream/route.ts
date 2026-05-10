// Proxies the browser's multipart upload through to the backend's
// `/v1/analyze/stream` and PASSES THROUGH the NDJSON stream — unlike
// the sibling `/api/analyze` route which buffers the whole body, this
// handler hands `upstream.body` (a ReadableStream) directly to the
// NextResponse so each stage event hits the browser as it lands.

import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";
// No `signal: AbortSignal.timeout(...)` here on purpose. AbortSignal.timeout
// keeps counting after the response headers arrive; once the deadline hits
// it tears the body stream down even if the backend is still emitting
// `stage` events on schedule. The streamed protocol already has the
// backend emit a terminal `result` or `error` event, plus its own
// per-stage timeouts, so a proxy-side hard timeout can only damage the
// happy path without adding any safety. CodeRabbit (PR #22) flagged the
// same issue on the sibling follow-up/stream route.

export const runtime = "nodejs";
// Disable Next's response buffering — without this, route handlers in
// production can buffer the upstream body until it closes, defeating
// the stream entirely.
export const dynamic = "force-dynamic";

export async function POST(request: NextRequest): Promise<Response> {
  let formData: FormData;
  try {
    formData = await request.formData();
  } catch {
    return NextResponse.json(
      { error: "invalid multipart payload" },
      { status: 400 },
    );
  }

  let upstream: Response;
  try {
    upstream = await fetch(`${BACKEND_URL}/v1/analyze/stream`, {
      method: "POST",
      body: formData,
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : "upstream failed";
    return NextResponse.json(
      { error: `backend unreachable: ${message}` },
      { status: 502 },
    );
  }

  // Hand the upstream's ReadableStream directly to the browser. Setting
  // `content-type` to NDJSON keeps clients from sniffing it as JSON
  // (which would block until EOF). `Cache-Control: no-store` matches
  // the backend so any intermediary proxy doesn't try to buffer.
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
