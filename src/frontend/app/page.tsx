const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";
const TIMEOUT_MS = 3000;

type BackendVersion = { name: string; version: string };

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
  // Only show the backend URL in development; in production this would leak
  // internal topology to anyone who loads the page.
  const debugSuffix =
    process.env.NODE_ENV === "development" ? ` @ ${BACKEND_URL}` : "";

  return (
    <main
      style={{
        maxWidth: 640,
        margin: "0 auto",
        padding: "6rem 1.5rem",
      }}
    >
      <h1 style={{ fontSize: "2rem", fontWeight: 600, margin: 0 }}>
        Hello, TableTalker
      </h1>
      <p style={{ color: "#555", marginTop: "0.75rem" }}>
        Skeleton frontend. Real UI lands in later PRs.
      </p>
      <pre
        style={{
          marginTop: "2rem",
          padding: "1rem",
          background: "#fff",
          border: "1px solid #eee",
          borderRadius: 8,
          fontSize: 13,
          overflowX: "auto",
        }}
      >
        {backend
          ? `backend: ${backend.name} v${backend.version}${debugSuffix}`
          : `backend: unreachable${debugSuffix}`}
      </pre>
    </main>
  );
}
