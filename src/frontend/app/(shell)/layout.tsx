// Server component shell shared by every page that lives behind the
// app's primary navigation. Two responsibilities:
//
//   1. Probe `/version` once on the server so we don't flash an
//      "unreachable" pill before the client has a chance to fetch
//      anything — the same pattern the original single-screen home
//      used, lifted up here so /history (and any future tab) gets it
//      without re-implementing.
//
//   2. Render the top chrome (`<TopBar />`) once. Pages render only
//      their main content; the topbar is sticky and shared, so a
//      route swap doesn't re-mount the navigation (no flash, no
//      backend-pill flicker on `/analyze` → `/history`).
//
// The route group `(shell)` exists so this layout is scoped to pages
// that want the chrome — a future "embed" page (e.g. raw report view)
// could live outside the group and skip the chrome entirely without
// touching root layout.

import type { ReactNode } from "react";

import { TopBar } from "../../components/TopBar";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";
const TIMEOUT_MS = 3000;

interface BackendVersion {
  name: string;
  version: string;
}

function isBackendVersion(value: unknown): value is BackendVersion {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate.name === "string" && typeof candidate.version === "string"
  );
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

export default async function ShellLayout({
  children,
}: {
  children: ReactNode;
}) {
  const backend = await fetchBackendVersion();
  // Only show the backend URL in development; in production this would
  // leak internal topology to anyone who loads the page.
  const debugSuffix =
    process.env.NODE_ENV === "development" ? ` @ ${BACKEND_URL}` : "";
  const label = backend
    ? `${backend.name} v${backend.version}${debugSuffix}`
    : `unreachable${debugSuffix}`;

  return (
    <>
      <TopBar backendOnline={Boolean(backend)} backendLabel={label} />
      {children}
    </>
  );
}
