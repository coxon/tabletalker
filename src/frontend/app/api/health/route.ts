import { NextResponse } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

export async function GET() {
  try {
    const response = await fetch(`${BACKEND_URL}/health`, { cache: "no-store" });
    const ok = response.ok && (await response.json()).ok === true;
    return NextResponse.json({ ok, backend: BACKEND_URL });
  } catch {
    return NextResponse.json({ ok: false, backend: BACKEND_URL }, { status: 503 });
  }
}
