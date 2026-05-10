export type BudgetRecommendation = {
  category_id: number;
  category_name: string;
  current_budget: number;
  recommended_budget: number;
  confidence_level: "low" | "medium" | "high" | "unavailable";
  behavior_group: string;
  cluster_label: string;
  reason: string;
  expected_change_amount: number;
  expected_change_percent: number;
  months_used: number;
};

export const BUDGET_RECOMMENDATIONS_ROUTE = "/budgets/recommendations";

export const formatCurrency = (value: number) =>
  value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export const formatSignedCurrency = (value: number) =>
  `${value >= 0 ? "+" : "-"}$${formatCurrency(Math.abs(value))}`;

export const formatPercent = (value: number) =>
  `${value >= 0 ? "+" : "-"}${Math.abs(value * 100).toFixed(1)}%`;

export const confidenceTone = (confidence: BudgetRecommendation["confidence_level"]) => {
  switch (confidence) {
    case "high":
      return "bg-green-100 text-green-800";
    case "medium":
      return "bg-blue-100 text-blue-800";
    case "low":
      return "bg-amber-100 text-amber-800";
    default:
      return "bg-slate-200 text-slate-700";
  }
};

export const confidenceLabel = (confidence: BudgetRecommendation["confidence_level"]) =>
  `${confidence.charAt(0).toUpperCase()}${confidence.slice(1)}`;
