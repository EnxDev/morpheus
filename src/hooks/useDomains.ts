import { useState, useEffect, useCallback } from "react";
import type { DomainConfig, DomainSummary } from "@/types/domain";

const API_BASE = "http://localhost:8000";

export interface UseDomainsReturn {
  domains: Record<string, DomainSummary>;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  registerDomain: (config: DomainConfig) => Promise<void>;
  deleteDomain: (name: string) => Promise<void>;
}

export function useDomains(): UseDomainsReturn {
  const [domains, setDomains] = useState<Record<string, DomainSummary>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await fetch(`${API_BASE}/api/domains`, {
        signal: AbortSignal.timeout(5000),
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      setDomains(data);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Failed to fetch domains";
      setError(
        msg.includes("Failed to fetch") || msg.includes("NetworkError") || msg.includes("TimeoutError")
          ? "Cannot reach backend on localhost:8000 — is it running?"
          : msg
      );
    } finally {
      setLoading(false);
    }
  }, []);

  const registerDomain = useCallback(async (config: DomainConfig) => {
    setLoading(true);
    setError(null);
    try {
      const resp = await fetch(`${API_BASE}/api/domains/register`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ config }),
      });
      if (!resp.ok) {
        const detail = await resp.json().catch(() => ({}));
        throw new Error(detail.detail || `HTTP ${resp.status}`);
      }
      await refresh();
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Failed to register domain";
      setError(msg);
      throw e;
    } finally {
      setLoading(false);
    }
  }, [refresh]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const deleteDomain = useCallback(async (name: string) => {
    setLoading(true);
    setError(null);
    try {
      const resp = await fetch(`${API_BASE}/api/domains/${encodeURIComponent(name)}`, {
        method: "DELETE",
      });
      if (!resp.ok) {
        const detail = await resp.json().catch(() => ({}));
        throw new Error(detail.detail || `HTTP ${resp.status}`);
      }
      await refresh();
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Failed to delete domain";
      setError(msg);
      throw e;
    } finally {
      setLoading(false);
    }
  }, [refresh]);

  return { domains, loading, error, refresh, registerDomain, deleteDomain };
}
