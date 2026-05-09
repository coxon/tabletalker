// Proxies the backend's `/reports/{id}.html` so the iframe in the UI
// loads from the same origin as the page. Without this proxy the
// iframe would have to embed `http://localhost:8000/...` directly,
// which (a) leaks topology and (b) means a deployment behind a
// reverse-proxy with a single public hostname can't host both halves.

import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";
const TIMEOUT_MS = 30_000;

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
): Promise<NextResponse> {
  const { id } = await params;
  // Strip a trailing `.html` if the caller appends one — the underlying
  // backend route already includes it. Belt-and-braces: also reject any
  // path-traversal attempts so a malformed id can't escape the
  // `/reports/` prefix on the upstream.
  const safeId = id.replace(/\.html$/i, "");
  if (!/^[A-Za-z0-9_-]+$/.test(safeId)) {
    return NextResponse.json({ error: "invalid report id" }, { status: 400 });
  }

  try {
    const upstream = await fetch(`${BACKEND_URL}/reports/${safeId}.html`, {
      cache: "no-store",
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
    const body = await upstream.text();
    return new NextResponse(body, {
      status: upstream.status,
      headers: {
        "content-type":
          upstream.headers.get("content-type") ?? "text/html; charset=utf-8",
      },
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : "upstream failed";
    return NextResponse.json(
      { error: `backend unreachable: ${message}` },
      { status: 502 },
    );
  }
}
