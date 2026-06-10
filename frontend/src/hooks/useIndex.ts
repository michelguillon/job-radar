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

  return { data, error, loading, refetch };
}
