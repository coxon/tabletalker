const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

type BackendVersion = { name: string; version: string };

async function fetchBackendVersion(): Promise<BackendVersion | null> {
  try {
    const response = await fetch(`${BACKEND_URL}/version`, { cache: "no-store" });
    if (!response.ok) return null;
    return (await response.json()) as BackendVersion;
  } catch {
    return null;
  }
}

export default async function Home() {
  const backend = await fetchBackendVersion();

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
          ? `backend: ${backend.name} v${backend.version} @ ${BACKEND_URL}`
          : `backend: unreachable @ ${BACKEND_URL}`}
      </pre>
    </main>
  );
}
