import { NextResponse } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";
const TIMEOUT_MS = 3000;

export async function GET() {
  try {
    const response = await fetch(`${BACKEND_URL}/health`, {
      cache: "no-store",
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
    if (!response.ok) {
      return NextResponse.json({ ok: false, backend: BACKEND_URL }, { status: 503 });
    }
    const data = (await response.json()) as { ok?: unknown };
    const ok = data.ok === true;
    return NextResponse.json({ ok, backend: BACKEND_URL }, { status: ok ? 200 : 503 });
  } catch {
    return NextResponse.json({ ok: false, backend: BACKEND_URL }, { status: 503 });
  }
}
