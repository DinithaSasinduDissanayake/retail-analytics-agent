import { useCallback, useEffect, useState } from "react";
import { RefreshCw, Play, Database, Table, AlertCircle, CheckCircle2 } from "lucide-react";
import { healthCheck, dashboardQuery, syncData, type HealthResponse, type DashboardResult } from "../lib/api";

type SyncStatus = "idle" | "syncing" | "done" | "error";

export default function DashboardPage() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [sql, setSql] = useState("SELECT * FROM Stock LIMIT 10");
  const [result, setResult] = useState<DashboardResult | null>(null);
  const [queryError, setQueryError] = useState<string | null>(null);
  const [queryLoading, setQueryLoading] = useState(false);
  const [syncStatus, setSyncStatus] = useState<SyncStatus>("idle");
  const [syncMessage, setSyncMessage] = useState("");

  /* Load health on mount */
  useEffect(() => {
    healthCheck()
      .then(setHealth)
      .catch(() => setHealth({ status: "error", detail: "Cannot reach server" }));
  }, []);

  /* Run a dashboard query */
  const handleRunQuery = useCallback(async () => {
    if (!sql.trim()) return;
    setQueryLoading(true);
    setQueryError(null);
    try {
      const res = await dashboardQuery(sql.trim());
      if (res.error) {
        setQueryError(res.error);
        setResult(null);
      } else {
        setResult(res);
      }
    } catch (err: unknown) {
      setQueryError(err instanceof Error ? err.message : "Query failed");
      setResult(null);
    } finally {
      setQueryLoading(false);
    }
  }, [sql]);

  /* Sync data */
  const handleSync = useCallback(async () => {
    setSyncStatus("syncing");
    setSyncMessage("Reloading data from POS export...");
    try {
      const res = await syncData();
      if (res.status === "ok") {
        setSyncStatus("done");
        setSyncMessage("Data refreshed successfully");
        // Refresh health
        const h = await healthCheck();
        setHealth(h);
      } else {
        setSyncStatus("error");
        setSyncMessage(res.summary?.error
          ? String(res.summary.error)
          : "Sync failed"
        );
      }
    } catch (err: unknown) {
      setSyncStatus("error");
      setSyncMessage(err instanceof Error ? err.message : "Sync request failed");
    }
    setTimeout(() => {
      setSyncStatus("idle");
      setSyncMessage("");
    }, 5000);
  }, []);

  return (
    <div className="h-full overflow-y-auto p-6 space-y-6">
      {/* Status bar */}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-gray-800 flex items-center gap-2">
          <Database size={20} className="text-blue-600" />
          Warehouse Dashboard
        </h2>
        <div className="flex items-center gap-3 text-sm">
          {health && (
            <span className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full ${
              health.status === "ok"
                ? "bg-green-50 text-green-700"
                : "bg-red-50 text-red-700"
            }`}>
              {health.status === "ok" ? (
                <CheckCircle2 size={14} />
              ) : (
                <AlertCircle size={14} />
              )}
              {health.status === "ok"
                ? `${health.products?.toLocaleString()} products`
                : "Offline"
              }
            </span>
          )}
          <button
            onClick={handleSync}
            disabled={syncStatus === "syncing"}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-gray-100 rounded-lg hover:bg-gray-200 disabled:opacity-50 text-gray-700 transition-colors"
          >
            <RefreshCw size={14} className={syncStatus === "syncing" ? "animate-spin" : ""} />
            {syncStatus === "syncing" ? "Syncing..." : "Sync"}
          </button>
        </div>
      </div>

      {syncMessage && (
        <div className={`text-sm px-4 py-2 rounded-lg ${
          syncStatus === "done"
            ? "bg-green-50 text-green-700"
            : syncStatus === "error"
            ? "bg-red-50 text-red-700"
            : "bg-blue-50 text-blue-700"
        }`}>
          {syncMessage}
        </div>
      )}

      {/* SQL query panel */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-100 bg-gray-50 flex items-center justify-between">
          <h3 className="text-sm font-medium text-gray-700 flex items-center gap-1.5">
            <Play size={14} className="text-green-600" />
            SQL Query
          </h3>
          <span className="text-xs text-gray-400">Read-only queries</span>
        </div>
        <div className="p-4 space-y-3">
          <textarea
            value={sql}
            onChange={(e) => setSql(e.target.value)}
            onKeyDown={(e) => {
              if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
                e.preventDefault();
                handleRunQuery();
              }
            }}
            rows={3}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono resize-y focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="Enter SQL query..."
          />
          <div className="flex items-center justify-between">
            <button
              onClick={handleRunQuery}
              disabled={queryLoading || !sql.trim()}
              className="flex items-center gap-1.5 px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50 transition-colors text-sm"
            >
              {queryLoading ? (
                <RefreshCw size={14} className="animate-spin" />
              ) : (
                <Play size={14} />
              )}
              Run (Ctrl+Enter)
            </button>
            {result && (
              <span className="text-xs text-gray-500">
                {result.count} row{result.count !== 1 ? "s" : ""}
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Query error */}
      {queryError && (
        <div className="bg-red-50 border border-red-200 rounded-xl px-4 py-3 flex items-start gap-2">
          <AlertCircle size={16} className="text-red-500 shrink-0 mt-0.5" />
          <span className="text-sm text-red-700">{queryError}</span>
        </div>
      )}

      {/* Results table */}
      {result && result.columns.length > 0 && (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-100 bg-gray-50 flex items-center gap-1.5">
            <Table size={14} className="text-blue-600" />
            <span className="text-sm font-medium text-gray-700">Results</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 border-b">
                  {result.columns.map((col) => (
                    <th
                      key={col}
                      className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider whitespace-nowrap"
                    >
                      {col}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {result.rows.map((row, i) => (
                  <tr key={i} className="hover:bg-gray-50">
                    {result.columns.map((col) => (
                      <td
                        key={col}
                        className="px-4 py-2 text-gray-700 whitespace-nowrap"
                      >
                        {String(row[col] ?? "")}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
