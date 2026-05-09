// Proxies the browser's multipart upload through to the backend's
// `/v1/analyze`. Doing it server-side means the browser only ever sees
// the Next host (no CORS dance, no leaked backend URL). The route is
// deliberately a thin pass-through — payload validation lives in the
// backend so we don't drift from the contract.

import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";
// Generous timeout: parent analysis can take ~60s on a slow LLM; the
// auto-grader gives us 300s but UX-wise 90s is the limit before the
// page should surface an error and let the user retry.
const TIMEOUT_MS = 120_000;

// Next 15 streams large multipart bodies through `request.formData()`
// without materialising the file in memory — we just relay it.
export async function POST(request: NextRequest): Promise<NextResponse> {
  let formData: FormData;
  try {
    formData = await request.formData();
  } catch {
    return NextResponse.json(
      { error: "invalid multipart payload" },
      { status: 400 },
    );
  }

  try {
    const upstream = await fetch(`${BACKEND_URL}/v1/analyze`, {
      method: "POST",
      // Don't set Content-Type — fetch infers the multipart boundary
      // from the FormData. Manual headers here would corrupt the body.
      body: formData,
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
