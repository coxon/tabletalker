// Proxy for `/v1/follow-up`. Mirrors `/api/analyze` — server-side so
// the browser never speaks to the backend directly. JSON in, JSON out.

import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";
const TIMEOUT_MS = 120_000;

export async function POST(request: NextRequest): Promise<NextResponse> {
  let payload: unknown;
  try {
    payload = await request.json();
  } catch {
    return NextResponse.json(
      { error: "invalid JSON payload" },
      { status: 400 },
    );
  }

  try {
    const upstream = await fetch(`${BACKEND_URL}/v1/follow-up`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
    const body = await upstream.text();
    return new NextResponse(body, {
      status: upstream.status,
      headers: { "content-type": upstream.headers.get("content-type") ?? "application/json" },
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : "upstream failed";
    return NextResponse.json(
      { error: `backend unreachable: ${message}` },
      { status: 502 },
    );
  }
}
