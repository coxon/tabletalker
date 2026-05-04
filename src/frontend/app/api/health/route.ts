import { NextResponse } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";
const TIMEOUT_MS = 3000;

// Only echo the backend URL back to clients in development. In production
// it would leak internal topology to anyone who probes /api/health.
const debugBackend =
  process.env.NODE_ENV === "development" ? { backend: BACKEND_URL } : {};

export async function GET() {
  try {
    const response = await fetch(`${BACKEND_URL}/health`, {
      cache: "no-store",
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
    if (!response.ok) {
      return NextResponse.json({ ok: false, ...debugBackend }, { status: 503 });
    }
    const data = (await response.json()) as { ok?: unknown };
    const ok = data.ok === true;
    return NextResponse.json({ ok, ...debugBackend }, { status: ok ? 200 : 503 });
  } catch {
    return NextResponse.json({ ok: false, ...debugBackend }, { status: 503 });
  }
}
