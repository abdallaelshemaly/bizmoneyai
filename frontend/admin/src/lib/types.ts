export type AdminSession = {
  admin_id: number;
  name: string;
  email: string;
  created_at: string;
};

export type AdminSortOrder = "asc" | "desc";

export type AdminPaginationMeta = {
  total: number;
  limit: number;
  offset: number;
  sort_by: string | null;
  sort_order: AdminSortOrder;
};

export type AdminCountByLabel = {
  label: string;
  count: number;
};

export type AdminActivityTrend = {
  date: string;
  users: number;
  transactions: number;
  categories: number;
  budgets: number;
  insights: number;
  logs: number;
  total_events: number;
};

export type AdminTransactionTrend = {
  date: string;
  transactions_count: number;
  total_amount: number;
};

export type AdminSpendDistributionItem = {
  category_name: string;
  total_amount: number;
  transactions_count: number;
};

export type AdminOverspendingCategory = {
  category_name: string;
  over_budget_count: number;
  total_overspent: number;
};

export type AdminActiveUser = {
  user_id: number;
  name: string;
  email: string;
  transactions_count: number;
  categories_count: number;
  budgets_count: number;
  insights_count: number;
  activity_score: number;
  last_activity: string | null;
};

export type AdminLogRow = {
  log_id: number;
  event_type: string;
  level: string;
  message: string;
  created_at: string;
  metadata: Record<string, unknown> | null;
  admin_id: number | null;
  admin_name: string | null;
  admin_email: string | null;
  user_id: number | null;
  user_name: string | null;
  user_email: string | null;
};

export type AdminUnusualTransactionInsight = {
  insight_id: number;
  user_id: number;
  user_name: string;
  user_email: string;
  title: string;
  message: string;
  severity: "warning" | "critical";
  period_start: string;
  period_end: string;
  created_at: string;
  transaction_id: number | null;
  fraud_probability: number | null;
};

export type AdminDashboard = {
  total_users: number;
  total_transactions: number;
  total_categories: number;
  total_budgets: number;
  total_ai_insights: number;
  activity_trends: AdminActivityTrend[];
  transaction_trends: AdminTransactionTrend[];
  insight_severity_distribution: AdminCountByLabel[];
  spend_distribution: AdminSpendDistributionItem[];
  top_overspending_categories: AdminOverspendingCategory[];
  most_active_users: AdminActiveUser[];
  over_budget_categories: number;
  total_overspending_amount: number;
  total_unusual_transactions: number;
  unusual_warning_count: number;
  unusual_critical_count: number;
  recent_unusual_transaction_insights: AdminUnusualTransactionInsight[];
  recent_logs: AdminLogRow[];
};

export type AdminAnalyticsOverview = Pick<
  AdminDashboard,
  "total_users" | "total_transactions" | "total_categories" | "total_budgets" | "total_ai_insights" | "activity_trends" | "recent_logs"
>;

export type AdminAnalyticsTransactions = Pick<
  AdminDashboard,
  "transaction_trends" | "spend_distribution"
>;

export type AdminAnalyticsUsers = Pick<AdminDashboard, "most_active_users">;

export type AdminAnalyticsInsights = Pick<
  AdminDashboard,
  "insight_severity_distribution" | "total_unusual_transactions" | "unusual_warning_count" | "unusual_critical_count" | "recent_unusual_transaction_insights"
>;

export type AdminAnalyticsBudgets = Pick<
  AdminDashboard,
  "top_overspending_categories" | "over_budget_categories" | "total_overspending_amount"
>;

export type AdminUserRow = {
  user_id: number;
  name: string;
  email: string;
  is_active: boolean;
  created_at: string;
  transactions_count: number;
  categories_count: number;
  budgets_count: number;
  insights_count: number;
  last_activity: string | null;
};

export type AdminUserSummary = {
  active_count: number;
  inactive_count: number;
};

export type AdminUsersResponse = AdminPaginationMeta & {
  users: AdminUserRow[];
  summary: AdminUserSummary;
};

export type AdminUserFinancialSummary = {
  total_income: number;
  total_expense: number;
  balance: number;
  over_budget_count: number;
};

export type AdminUserOverview = {
  user: AdminUserRow;
  financial_summary: AdminUserFinancialSummary;
  recent_logs: AdminLogRow[];
  recent_insights: AdminInsightRow[];
};

export type AdminTransactionRow = {
  transaction_id: number;
  user_id: number;
  user_name: string;
  user_email: string;
  category_id: number;
  category_name: string;
  amount: number;
  type: "income" | "expense";
  description: string | null;
  date: string;
  created_at: string;
  fraud_risk_level: "warning" | "critical" | null;
  fraud_probability: number | null;
  fraud_insight_id: number | null;
};

export type AdminTransactionSummary = {
  total_amount: number;
  income_count: number;
  expense_count: number;
};

export type AdminTransactionsResponse = AdminPaginationMeta & {
  transactions: AdminTransactionRow[];
  summary: AdminTransactionSummary;
};

export type AdminCategoryRow = {
  category_id: number;
  user_id: number;
  user_name: string;
  user_email: string;
  name: string;
  type: "income" | "expense" | "both";
  transactions_count: number;
  budgets_count: number;
  created_at: string;
};

export type AdminCategorySummary = {
  income_count: number;
  expense_count: number;
  both_count: number;
};

export type AdminCategoriesResponse = AdminPaginationMeta & {
  categories: AdminCategoryRow[];
  summary: AdminCategorySummary;
};

export type AdminDefaultCategoryOut = {
  user_id: number;
  category_id: number;
  name: string;
  type: "income" | "expense" | "both";
};

export type AdminDefaultCategoriesResult = {
  target_user_count: number;
  created_count: number;
  created: AdminDefaultCategoryOut[];
};

export type AdminBudgetRow = {
  budget_id: number;
  user_id: number;
  user_name: string;
  user_email: string;
  category_id: number;
  category_name: string;
  amount: number;
  spent: number;
  remaining: number;
  status: "on_track" | "near_limit" | "over";
  month: string;
  note: string | null;
  created_at: string;
};

export type AdminOverspendingAnalysis = {
  over_budget_count: number;
  near_limit_count: number;
  total_budgeted: number;
  total_spent: number;
  total_overspent: number;
};

export type AdminPopularCategory = {
  category_name: string;
  budget_count: number;
  total_budgeted: number;
  total_spent: number;
};

export type AdminBudgetTrend = {
  month: string;
  budgets_count: number;
  total_budgeted: number;
  total_spent: number;
  over_budget_count: number;
};

export type AdminBudgetsResponse = AdminPaginationMeta & {
  budgets: AdminBudgetRow[];
  overspending_analysis: AdminOverspendingAnalysis;
  popular_categories: AdminPopularCategory[];
  budget_trends: AdminBudgetTrend[];
};

export type AdminInsightRow = {
  insight_id: number;
  user_id: number;
  user_name: string;
  user_email: string;
  title: string;
  message: string;
  severity: "info" | "warning" | "critical";
  period_start: string;
  period_end: string;
  created_at: string;
};

export type AdminInsightsResponse = AdminPaginationMeta & {
  insights: AdminInsightRow[];
  severity_distribution: AdminCountByLabel[];
  trigger_frequency: AdminCountByLabel[];
};

export type AdminLogSummary = {
  warning_count: number;
  error_count: number;
};

export type AdminLogsResponse = AdminPaginationMeta & {
  logs: AdminLogRow[];
  summary: AdminLogSummary;
};
