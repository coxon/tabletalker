// Server component shell. Backend reachability resolves on the server
// so we don't flash an "unreachable" pill before client-side fetch
// lands. Everything stateful below this lives in `AnalyzeShell` (a
// client island).

import { AnalyzeShell } from "../components/AnalyzeShell";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";
const TIMEOUT_MS = 3000;

interface BackendVersion {
  name: string;
  version: string;
}

function isBackendVersion(value: unknown): value is BackendVersion {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Record<string, unknown>;
  return typeof candidate.name === "string" && typeof candidate.version === "string";
}

async function fetchBackendVersion(): Promise<BackendVersion | null> {
  try {
    const response = await fetch(`${BACKEND_URL}/version`, {
      cache: "no-store",
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
    if (!response.ok) return null;
    const parsed: unknown = await response.json();
    return isBackendVersion(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

export default async function Home() {
  const backend = await fetchBackendVersion();
  // Only show the backend URL in development; in production this would
  // leak internal topology to anyone who loads the page.
  const debugSuffix =
    process.env.NODE_ENV === "development" ? ` @ ${BACKEND_URL}` : "";
  const label = backend
    ? `${backend.name} v${backend.version}${debugSuffix}`
    : `unreachable${debugSuffix}`;

  return (
    <AnalyzeShell backendOnline={Boolean(backend)} backendLabel={label} />
  );
}
