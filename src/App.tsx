import { useEffect, useState } from "react";

export default function App() {
  const [status, setStatus] = useState<string>("Initializing...");

  useEffect(() => {
    fetch("http://localhost:9721/api/health")
      .then((r) => r.json())
      .then((data) => setStatus(`Backend: ${data.status}`))
      .catch(() => setStatus("Backend offline (expected in Phase 1)"));
  }, []);

  return (
    <div className="flex items-center justify-center w-full h-full">
      <div className="text-center">
        <h1 className="text-5xl font-bold tracking-tight text-text-primary mb-3">
          Engram
        </h1>
        <p className="text-lg text-text-secondary mb-6">
          Neural graph for your coding projects
        </p>
        <p className="text-sm text-text-muted font-mono">{status}</p>
      </div>
    </div>
  );
}
