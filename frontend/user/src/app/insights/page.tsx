"use client";

import axios from "axios";
import { useEffect, useState } from "react";

import Navbar from "@/components/Navbar";
import { useAuth } from "@/hooks/useAuth";
import api from "@/lib/api";

type Insight = {
  insight_id: number;
  rule_id: string | null;
  title: string;
  message: string;
  severity: "info" | "warning" | "critical";
  period_start: string;
  period_end: string;
  created_at: string;
};

const CARD = { info: "bg-blue-50 border-blue-200", warning: "bg-yellow-50 border-yellow-200", critical: "bg-red-50 border-red-200" };
const TXT = { info: "text-blue-800", warning: "text-yellow-800", critical: "text-red-800" };
const BADGE = { info: "bg-blue-100 text-blue-700", warning: "bg-yellow-100 text-yellow-700", critical: "bg-red-100 text-red-700" };
const today = new Date().toISOString().slice(0, 10);
const defaultStart = new Date(Date.now() - 29 * 24 * 60 * 60 * 1000).toISOString().slice(0, 10);

function readableApiError(error: unknown, fallback: string) {
  if (!axios.isAxiosError(error)) return fallback;

  const detail = error.response?.data?.detail;
  if (typeof detail === "string" && detail.trim()) return detail;
  if (!error.response) return "Could not reach the API. Check that the backend is running and try again.";
  return fallback;
}

export default function InsightsPage() {
  const { user, loading } = useAuth();
  const [insights, setInsights] = useState<Insight[]>([]);
  const [loadingInsights, setLoadingInsights] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [gen, setGen] = useState(false);
  const [msg, setMsg] = useState("");
  const [periodStart, setPeriodStart] = useState(defaultStart);
  const [periodEnd, setPeriodEnd] = useState(today);
  const [severityFilter, setSeverityFilter] = useState<"all" | "info" | "warning" | "critical">("all");

  const refresh = async () => {
    setLoadingInsights(true);
    setLoadError("");
    try {
      const r = await api.get<Insight[]>("/ai/insights");
      setInsights(r.data);
    } catch (error) {
      setLoadError(readableApiError(error, "Failed to load insights."));
    } finally {
      setLoadingInsights(false);
    }
  };

  useEffect(() => {
    if (!user) return;
    void refresh();
  }, [user]);

  const generate = async () => {
    if (periodStart && periodEnd && periodStart > periodEnd) {
      setMsg("Start date must be on or before end date.");
      return;
    }

    setGen(true);
    setMsg("");
    try {
      const payload = { period_start: periodStart || undefined, period_end: periodEnd || undefined };
      const r = await api.post<Insight[]>("/ai/generate", payload);
      setMsg(
        r.data.length === 0
          ? "No new insights were generated for this period. Your finances may be stable, or you may need more transactions recorded."
          : `Generated ${r.data.length} new insight(s) for ${periodStart} to ${periodEnd}.`,
      );
      await refresh();
    } catch (error) {
      setMsg(readableApiError(error, "Failed to generate insights."));
    } finally {
      setGen(false);
    }
  };

  if (loading) {
    return <div className="flex min-h-screen items-center justify-center text-slate-400">Loading...</div>;
  }

  const filteredInsights = severityFilter === "all" ? insights : insights.filter((ins) => ins.severity === severityFilter);
  const counts = {
    all: insights.length,
    critical: insights.filter((ins) => ins.severity === "critical").length,
    warning: insights.filter((ins) => ins.severity === "warning").length,
    info: insights.filter((ins) => ins.severity === "info").length,
  };

  return (
    <>
      <Navbar userName={user?.name} />
      <main className="mx-auto max-w-4xl space-y-8 p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="text-3xl font-bold text-ink">AI Insights</h1>
          </div>
          <div className="flex flex-wrap items-end gap-3">
            <div>
              <label className="mb-1 block text-xs text-slate-500">Period start</label>
              <input type="date" value={periodStart} onChange={(e) => setPeriodStart(e.target.value)} className="text-sm" />
            </div>
            <div>
              <label className="mb-1 block text-xs text-slate-500">Period end</label>
              <input type="date" value={periodEnd} onChange={(e) => setPeriodEnd(e.target.value)} className="text-sm" />
            </div>
            <button onClick={generate} disabled={gen} className="min-w-[180px]">
              {gen ? "Analyzing..." : "Generate Insights"}
            </button>
          </div>
        </div>

        {msg && <div className="rounded-lg bg-slate-100 px-4 py-3 text-sm text-slate-700">{msg}</div>}
        {loadError && (
          <div role="alert" className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
            <span>{loadError}</span>
            <button type="button" onClick={() => void refresh()} className="bg-red-100 text-red-800 hover:bg-red-200">
              Retry
            </button>
          </div>
        )}

        <div className="flex flex-wrap gap-2">
          {([
            ["all", "All"],
            ["critical", "Critical"],
            ["warning", "Warning"],
            ["info", "Info"],
          ] as const).map(([value, label]) => (
            <button
              key={value}
              type="button"
              onClick={() => setSeverityFilter(value)}
              className={severityFilter === value ? "bg-ink text-white" : "bg-slate-100 text-slate-700 hover:bg-slate-200"}
            >
              {label} ({counts[value]})
            </button>
          ))}
        </div>

        {loadingInsights && insights.length === 0 ? (
          <div className="rounded-xl border border-dashed border-slate-300 p-12 text-center">
            <p className="text-lg text-slate-400">Loading insights...</p>
          </div>
        ) : filteredInsights.length === 0 ? (
          <div className="rounded-xl border border-dashed border-slate-300 p-12 text-center">
            <p className="text-lg text-slate-400">{insights.length === 0 ? "No insights yet." : "No insights match this filter."}</p>
          </div>
        ) : (
          <div className="space-y-4">
            {filteredInsights.map((ins) => (
              <div key={ins.insight_id} className={`rounded-xl border p-5 ${CARD[ins.severity]}`}>
                <div className="flex items-start gap-3">
                  <div className="flex-1">
                    <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
                      <h3 className={`font-semibold ${TXT[ins.severity]}`}>{ins.title}</h3>
                      <div className="flex flex-wrap gap-2">
                        {ins.rule_id === "ml_unusual_transaction" && (
                          <span className="rounded-full bg-slate-900 px-2.5 py-0.5 text-xs font-medium text-white">
                            Model 2
                          </span>
                        )}
                        <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${BADGE[ins.severity]}`}>
                          {ins.severity.toUpperCase()}
                        </span>
                      </div>
                    </div>
                    <p className={`text-sm ${TXT[ins.severity]}`}>{ins.message}</p>
                    <p className="mt-2 text-xs text-slate-400">
                      Period: {ins.period_start} to {ins.period_end} | Generated: {new Date(ins.created_at).toLocaleString()}
                    </p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </main>
    </>
  );
}
