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
  priority_score?: number;
  priority_level?: "low" | "medium" | "high" | "critical";
  priority_reason?: string;
};

const CARD = { info: "bg-blue-50 border-blue-200", warning: "bg-yellow-50 border-yellow-200", critical: "bg-red-50 border-red-200" };
const TXT = { info: "text-blue-800", warning: "text-yellow-800", critical: "text-red-800" };
const BADGE = { info: "bg-blue-100 text-blue-700", warning: "bg-yellow-100 text-yellow-700", critical: "bg-red-100 text-red-700" };
const PRIORITY_BADGE = {
  critical: "bg-rose-100 text-rose-700",
  high: "bg-orange-100 text-orange-700",
  medium: "bg-sky-100 text-sky-700",
  low: "bg-slate-200 text-slate-700",
};
const today = new Date().toISOString().slice(0, 10);
const defaultStart = new Date(Date.now() - 29 * 24 * 60 * 60 * 1000).toISOString().slice(0, 10);

function isFullMonthSpan(start: string, end: string) {
  if (!start || !end) return false;
  const startDate = new Date(`${start}T00:00:00`);
  const endDate = new Date(`${end}T00:00:00`);
  if (Number.isNaN(startDate.getTime()) || Number.isNaN(endDate.getTime())) return false;
  const startMonthFirst = new Date(startDate.getFullYear(), startDate.getMonth(), 1);
  const endMonthLast = new Date(endDate.getFullYear(), endDate.getMonth() + 1, 0);
  return startDate.getTime() === startMonthFirst.getTime() && endDate.getTime() === endMonthLast.getTime();
}

function suggestFullMonthRange(start: string, end: string) {
  if (!start || !end) return null;
  const startDate = new Date(`${start}T00:00:00`);
  const endDate = new Date(`${end}T00:00:00`);
  if (Number.isNaN(startDate.getTime()) || Number.isNaN(endDate.getTime())) return null;
  const suggestedStart = new Date(startDate.getFullYear(), startDate.getMonth(), 1).toISOString().slice(0, 10);
  const suggestedEnd = new Date(endDate.getFullYear(), endDate.getMonth() + 1, 0).toISOString().slice(0, 10);
  return { suggestedStart, suggestedEnd };
}

function priorityLabel(level?: Insight["priority_level"]) {
  if (!level) return null;
  return `${level.charAt(0).toUpperCase()}${level.slice(1)} priority`;
}

function displayInsightMessage(insight: Insight) {
  if (insight.rule_id !== "ml_unusual_transaction") return insight.message;
  if (insight.severity === "critical") {
    return "A high-risk unusual transaction was detected. This transaction is significantly outside your normal spending pattern and may require immediate review.";
  }
  if (insight.severity === "warning") {
    return "An unusual transaction was detected. Review this transaction to confirm it matches your expected business activity.";
  }
  return insight.message;
}

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
      const rankedResponse = await api.get<Insight[]>("/ai/insights/ranked");
      setInsights(rankedResponse.data);
    } catch (error) {
      try {
        const fallbackResponse = await api.get<Insight[]>("/ai/insights");
        setInsights(fallbackResponse.data);
      } catch (fallbackError) {
        setLoadError(readableApiError(fallbackError, "Failed to load insights."));
      }
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
  const fullMonthSuggestion = suggestFullMonthRange(periodStart, periodEnd);
  const isPartialPeriodSelection = periodStart !== "" && periodEnd !== "" && !isFullMonthSpan(periodStart, periodEnd);
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

        {isPartialPeriodSelection && fullMonthSuggestion && (
          <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <span>
                Partial ranges can understate income and profit. Month-over-month drop rules only run for full calendar months. Try{" "}
                <strong>
                  {fullMonthSuggestion.suggestedStart} to {fullMonthSuggestion.suggestedEnd}
                </strong>
                .
              </span>
              <button
                type="button"
                onClick={() => {
                  setPeriodStart(fullMonthSuggestion.suggestedStart);
                  setPeriodEnd(fullMonthSuggestion.suggestedEnd);
                }}
                className="bg-amber-100 text-amber-900 hover:bg-amber-200"
              >
                Use full months
              </button>
            </div>
          </div>
        )}

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
                        <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${BADGE[ins.severity]}`}>
                          {ins.severity.toUpperCase()}
                        </span>
                        {ins.priority_level && (
                          <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${PRIORITY_BADGE[ins.priority_level]}`}>
                            {priorityLabel(ins.priority_level)}
                          </span>
                        )}
                      </div>
                    </div>
                    <p className={`text-sm ${TXT[ins.severity]}`}>{displayInsightMessage(ins)}</p>
                    {ins.priority_reason && <p className="mt-2 text-xs text-slate-500">{ins.priority_reason}</p>}
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
