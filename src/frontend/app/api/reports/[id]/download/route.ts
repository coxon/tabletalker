import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";
const TIMEOUT_MS = 30_000;

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
): Promise<NextResponse> {
  const { id } = await params;
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
        "content-disposition": `attachment; filename="tabletalker-report-${safeId}.html"`,
        "cache-control": "no-store",
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
