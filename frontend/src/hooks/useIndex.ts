import { useCallback, useEffect, useState } from "react";
import { api, type IndexResponse } from "@/lib/api";

// Fetches GET /api/index (the joined read model with the live activity-log overlay).
// refetch() is called after every successful write so the UI reflects state without a
// re-score — the backend re-projects the log per request (job_radar_SPEC §10.4).
export function useIndex() {
  const [data, setData] = useState<IndexResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const refetch = useCallback(async () => {
    try {
      setData(await api.index());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refetch();
  }, [refetch]);

  // Live updates (job_radar_SPEC §11.1), two complementary signals:
  //  A. Tab focus — re-fetch when the tab regains visibility (e.g. switching back from
  //     cv-tailor after recording a result). Covers the primary "came back" case instantly.
  //  B. SSE — GET /api/events emits index_updated after any write (here or from the cv-tailor
  //     callback), so a tab left open refreshes in the background without a manual reload.
  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === "visible") void refetch();
    };
    document.addEventListener("visibilitychange", onVisible);

    const es = new EventSource("/api/events");
    es.addEventListener("index_updated", () => void refetch());

    return () => {
      document.removeEventListener("visibilitychange", onVisible);
      es.close();
    };
  }, [refetch]);

  return { data, error, loading, refetch };
}
