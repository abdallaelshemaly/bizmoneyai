from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from numbers import Number
from typing import Any, Callable

import yaml

from app.services.insights.calculator import CategoryTotals, InsightCalculationContext

RULES_PATH = Path(__file__).resolve().parents[3] / "rules" / "rules.yaml"
SEVERITY_ORDER = {"info": 0, "warning": 1, "critical": 2}
SUPPORTED_SCOPES = {"period", "category_period"}
RULE_TYPE_ALIASES = {
    "expense_ratio_gt": "expense_ratio",
    "profit_drop_percent_gt": "profit_drop_percent",
    "spending_spike_percent_gt": "spending_spike_percent",
    "category_budget_usage_gte": "budget_overspend_ratio",
    "category_income_ratio_gt": "category_income_ratio",
    "income_drop_percent_gt": "income_drop_percent",
    "consecutive_budget_overspend_gte": "consecutive_budget_overspend",
}
SUPPORTED_RULE_TYPES = {
    "expense_ratio",
    "profit_drop_percent",
    "spending_spike_percent",
    "budget_overspend_ratio",
    "category_income_ratio",
    "income_drop_percent",
    "missing_budget_high_spend",
    "consecutive_budget_overspend",
    "negative_balance",
    "negative_balance_below",
    "zero_income_with_expense",
}


@dataclass(frozen=True)
class RuleConfig:
    rule_id: str
    rule_type: str
    enabled: bool
    scope: str
    severity_thresholds: dict[str, float]
    titles: dict[str, str] = field(default_factory=dict)
    message_template: str | None = None
    message_templates: dict[str, str] = field(default_factory=dict)
    category_names: tuple[str, ...] = ()
    settings: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Ruleset:
    defaults: dict[str, Any]
    rules: tuple[RuleConfig, ...]


@dataclass(frozen=True)
class InsightCandidate:
    rule_id: str
    severity: str
    title: str
    message: str
    metadata: dict[str, Any]
    scope_key: str = "period"


def clear_rules_cache() -> None:
    load_ruleset.cache_clear()


@lru_cache(maxsize=1)
def load_ruleset() -> Ruleset:
    with open(RULES_PATH, "r", encoding="utf-8") as fh:
        raw_config = yaml.safe_load(fh) or {}

    _validate_raw_rules_config(raw_config)
    defaults = dict(raw_config.get("defaults") or {})
    rules = tuple(_normalize_rules(raw_config.get("rules") or []))
    return Ruleset(defaults=defaults, rules=rules)


def evaluate_rules(
    context: InsightCalculationContext,
    *,
    ruleset: Ruleset | None = None,
) -> list[InsightCandidate]:
    active_ruleset = ruleset or load_ruleset()
    candidates: list[InsightCandidate] = []
    for rule in active_ruleset.rules:
        if not rule.enabled:
            continue
        evaluator = RULE_EVALUATORS.get(rule.rule_type)
        if evaluator is None:
            continue
        candidates.extend(evaluator(rule, context, active_ruleset.defaults))
    return candidates


def _normalize_rules(raw_rules: list[dict[str, Any]]) -> list[RuleConfig]:
    normalized: list[RuleConfig] = []
    grouped: dict[tuple[Any, ...], dict[str, Any]] = {}
    ordered_group_keys: list[tuple[Any, ...]] = []

    for raw_rule in raw_rules:
        if not isinstance(raw_rule, dict):
            continue

        normalized_type = _canonical_rule_type(raw_rule.get("type"))
        category_names = _extract_category_names(raw_rule)
        scope = str(raw_rule.get("scope") or _default_scope(normalized_type)).strip().lower()

        if raw_rule.get("severity_thresholds"):
            normalized.append(
                _build_rule_config(
                    rule_id=str(raw_rule.get("id") or normalized_type),
                    rule_type=normalized_type,
                    enabled=bool(raw_rule.get("enabled", True)),
                    scope=scope,
                    severity_thresholds=raw_rule.get("severity_thresholds") or {},
                    titles=raw_rule.get("titles") or {},
                    message_template=raw_rule.get("message_template"),
                    message_templates=raw_rule.get("message_templates") or {},
                    category_names=category_names,
                    settings=_extra_rule_settings(raw_rule),
                )
            )
            continue

        severity = str(raw_rule.get("severity") or "").lower()
        threshold = raw_rule.get("threshold")
        if severity not in SEVERITY_ORDER or threshold is None:
            continue

        base_rule_id = str(raw_rule.get("dedup_key") or raw_rule.get("id") or normalized_type)
        group_key = (base_rule_id, normalized_type, scope, category_names)
        if group_key not in grouped:
            grouped[group_key] = {
                "rule_id": base_rule_id,
                "rule_type": normalized_type,
                "enabled": bool(raw_rule.get("enabled", True)),
                "scope": scope,
                "severity_thresholds": {},
                "titles": {},
                "message_templates": {},
                "category_names": category_names,
                "settings": _extra_rule_settings(raw_rule),
            }
            ordered_group_keys.append(group_key)

        grouped_rule = grouped[group_key]
        grouped_rule["severity_thresholds"][severity] = float(threshold)
        if raw_rule.get("title"):
            grouped_rule["titles"][severity] = str(raw_rule["title"])
        template = raw_rule.get("message_template") or raw_rule.get("message")
        if template:
            grouped_rule["message_templates"][severity] = str(template)

    for group_key in ordered_group_keys:
        grouped_rule = grouped[group_key]
        normalized.append(
            _build_rule_config(
                rule_id=grouped_rule["rule_id"],
                rule_type=grouped_rule["rule_type"],
                enabled=grouped_rule["enabled"],
                scope=grouped_rule["scope"],
                severity_thresholds=grouped_rule["severity_thresholds"],
                titles=grouped_rule["titles"],
                message_template=None,
                message_templates=grouped_rule["message_templates"],
                category_names=grouped_rule["category_names"],
                settings=grouped_rule["settings"],
            )
        )

    return normalized


def _build_rule_config(
    *,
    rule_id: str,
    rule_type: str,
    enabled: bool,
    scope: str,
    severity_thresholds: dict[str, Any],
    titles: dict[str, Any],
    message_template: str | None,
    message_templates: dict[str, Any],
    category_names: tuple[str, ...],
    settings: dict[str, Any],
) -> RuleConfig:
    normalized_thresholds = {
        severity: float(threshold)
        for severity, threshold in severity_thresholds.items()
        if severity in SEVERITY_ORDER and threshold is not None
    }
    normalized_titles = {severity: str(title) for severity, title in titles.items() if severity in SEVERITY_ORDER}
    normalized_message_templates = {
        severity: str(template)
        for severity, template in message_templates.items()
        if severity in SEVERITY_ORDER and template is not None
    }
    return RuleConfig(
        rule_id=rule_id,
        rule_type=rule_type,
        enabled=enabled,
        scope=scope,
        severity_thresholds=normalized_thresholds,
        titles=normalized_titles,
        message_template=str(message_template) if message_template is not None else None,
        message_templates=normalized_message_templates,
        category_names=category_names,
        settings=settings,
    )


def _extra_rule_settings(raw_rule: dict[str, Any]) -> dict[str, Any]:
    ignored_keys = {
        "id",
        "type",
        "enabled",
        "scope",
        "threshold",
        "severity",
        "severity_thresholds",
        "title",
        "titles",
        "message",
        "message_template",
        "message_templates",
        "category",
        "categories",
        "dedup_key",
    }
    return {key: value for key, value in raw_rule.items() if key not in ignored_keys}


def _extract_category_names(raw_rule: dict[str, Any]) -> tuple[str, ...]:
    raw_categories = raw_rule.get("categories")
    if raw_categories is None and raw_rule.get("category") is not None:
        raw_categories = [raw_rule["category"]]
    if raw_categories is None:
        return ()
    if isinstance(raw_categories, str):
        raw_categories = [raw_categories]
    return tuple(sorted(str(item).strip().lower() for item in raw_categories if str(item).strip()))


def _canonical_rule_type(raw_rule_type: Any) -> str:
    rule_type = str(raw_rule_type or "").strip().lower()
    return RULE_TYPE_ALIASES.get(rule_type, rule_type)


def _default_scope(rule_type: str) -> str:
    if rule_type in {
        "budget_overspend_ratio",
        "category_income_ratio",
        "missing_budget_high_spend",
        "consecutive_budget_overspend",
    }:
        return "category_period"
    return "period"


def _evaluate_expense_ratio(
    rule: RuleConfig,
    context: InsightCalculationContext,
    defaults: dict[str, Any],
) -> list[InsightCandidate]:
    if context.current.total_expense <= 0:
        return []

    min_income = float(defaults.get("min_income_for_ratio_rules", 0.0) or 0.0)
    if context.current.total_income <= min_income:
        return []

    expense_ratio = context.current.expense_ratio
    if expense_ratio is None:
        return []

    severity = _resolve_severity(rule, expense_ratio)
    if severity is None:
        return []

    return [
        _candidate(
            rule,
            severity=severity,
            metadata={
                "scope": rule.scope,
                "scope_key": "period",
                "expense_ratio": round(expense_ratio, 4),
                "current_income": round(context.current.total_income, 2),
                "current_expense": round(context.current.total_expense, 2),
            },
            format_context={
                "expense_ratio_pct": _format_ratio_percent(expense_ratio),
                "total_income_amount": _format_amount(context.current.total_income, defaults),
                "total_expense_amount": _format_amount(context.current.total_expense, defaults),
            },
        )
    ]


def _evaluate_profit_drop_percent(
    rule: RuleConfig,
    context: InsightCalculationContext,
    defaults: dict[str, Any],
) -> list[InsightCandidate]:
    comparison = context.monthly_comparison
    if comparison is None:
        return []

    previous_profit = comparison.previous.balance
    current_profit = comparison.current.balance
    if previous_profit <= 0 or current_profit >= previous_profit:
        return []

    drop_pct = ((previous_profit - current_profit) / previous_profit) * 100
    severity = _resolve_severity(rule, drop_pct)
    if severity is None:
        return []

    return [
        _candidate(
            rule,
            severity=severity,
            metadata={
                "scope": rule.scope,
                "scope_key": "period",
                "profit_drop_percent": round(drop_pct, 2),
                "current_profit": round(current_profit, 2),
                "previous_profit": round(previous_profit, 2),
            },
            format_context={
                "profit_drop_pct": _format_percent(drop_pct),
                "current_profit_amount": _format_amount(current_profit, defaults),
                "previous_profit_amount": _format_amount(previous_profit, defaults),
            },
        )
    ]


def _evaluate_spending_spike_percent(
    rule: RuleConfig,
    context: InsightCalculationContext,
    defaults: dict[str, Any],
) -> list[InsightCandidate]:
    previous_expense = context.previous.total_expense
    current_expense = context.current.total_expense
    if previous_expense <= 0 or current_expense <= previous_expense:
        return []

    spike_pct = ((current_expense - previous_expense) / previous_expense) * 100
    severity = _resolve_severity(rule, spike_pct)
    if severity is None:
        return []

    return [
        _candidate(
            rule,
            severity=severity,
            metadata={
                "scope": rule.scope,
                "scope_key": "period",
                "spending_spike_percent": round(spike_pct, 2),
                "current_expense": round(current_expense, 2),
                "previous_expense": round(previous_expense, 2),
            },
            format_context={
                "spending_spike_pct": _format_percent(spike_pct),
                "current_expense_amount": _format_amount(current_expense, defaults),
                "previous_expense_amount": _format_amount(previous_expense, defaults),
            },
        )
    ]


def _evaluate_budget_overspend_ratio(
    rule: RuleConfig,
    context: InsightCalculationContext,
    defaults: dict[str, Any],
) -> list[InsightCandidate]:
    candidates: list[InsightCandidate] = []
    for budget in context.current_budgets:
        usage_ratio = budget.usage_ratio
        if usage_ratio is None:
            continue

        severity = _resolve_severity(rule, usage_ratio)
        if severity is None:
            continue

        scope_key = _category_month_scope_key(budget.category_id, budget.month)
        candidates.append(
            _candidate(
                rule,
                severity=severity,
                scope_key=scope_key,
                metadata={
                    "scope": rule.scope,
                    "scope_key": scope_key,
                    "category_id": budget.category_id,
                    "category_name": budget.category_name,
                    "budget_month": budget.month.isoformat(),
                    "budget_amount": round(budget.amount, 2),
                    "budget_spent": round(budget.spent, 2),
                    "budget_usage_ratio": round(usage_ratio, 4),
                    "overspend_amount": round(budget.overspend_amount, 2),
                },
                format_context={
                    "category_name": budget.category_name,
                    "budget_month_label": _month_label(budget.month),
                    "budget_usage_pct": _format_ratio_percent(usage_ratio),
                    "budget_amount": _format_amount(budget.amount, defaults),
                    "budget_spent_amount": _format_amount(budget.spent, defaults),
                    "overspend_amount": _format_amount(budget.overspend_amount, defaults),
                },
            )
        )
    return candidates


def _evaluate_category_income_ratio(
    rule: RuleConfig,
    context: InsightCalculationContext,
    defaults: dict[str, Any],
) -> list[InsightCandidate]:
    if context.current.total_income <= 0:
        return []

    candidates: list[InsightCandidate] = []
    for category in _iter_current_expense_categories(context.current):
        if not _category_allowed(rule, category):
            continue
        if category.expense_total <= 0:
            continue

        ratio_value = category.expense_total / context.current.total_income
        severity = _resolve_severity(rule, ratio_value)
        if severity is None:
            continue

        scope_key = _category_scope_key(category.category_id)
        candidates.append(
            _candidate(
                rule,
                severity=severity,
                scope_key=scope_key,
                metadata={
                    "scope": rule.scope,
                    "scope_key": scope_key,
                    "category_id": category.category_id,
                    "category_name": category.category_name,
                    "category_spend": round(category.expense_total, 2),
                    "current_income": round(context.current.total_income, 2),
                    "category_income_ratio": round(ratio_value, 4),
                },
                format_context={
                    "category_name": category.category_name,
                    "category_spend_amount": _format_amount(category.expense_total, defaults),
                    "total_income_amount": _format_amount(context.current.total_income, defaults),
                    "category_income_ratio_pct": _format_ratio_percent(ratio_value),
                },
            )
        )
    return candidates


def _evaluate_income_drop_percent(
    rule: RuleConfig,
    context: InsightCalculationContext,
    defaults: dict[str, Any],
) -> list[InsightCandidate]:
    comparison = context.monthly_comparison
    if comparison is None:
        return []

    previous_income = comparison.previous.total_income
    current_income = comparison.current.total_income
    if previous_income <= 0 or current_income >= previous_income:
        return []

    drop_pct = ((previous_income - current_income) / previous_income) * 100
    severity = _resolve_severity(rule, drop_pct)
    if severity is None:
        return []

    return [
        _candidate(
            rule,
            severity=severity,
            metadata={
                "scope": rule.scope,
                "scope_key": "period",
                "income_drop_percent": round(drop_pct, 2),
                "current_income": round(current_income, 2),
                "previous_income": round(previous_income, 2),
            },
            format_context={
                "income_drop_pct": _format_percent(drop_pct),
                "current_income_amount": _format_amount(current_income, defaults),
                "previous_income_amount": _format_amount(previous_income, defaults),
            },
        )
    ]


def _evaluate_missing_budget_high_spend(
    rule: RuleConfig,
    context: InsightCalculationContext,
    defaults: dict[str, Any],
) -> list[InsightCandidate]:
    candidates: list[InsightCandidate] = []
    for expense_snapshot in context.current_monthly_expenses:
        budget_key = (expense_snapshot.category_id, expense_snapshot.month)
        if budget_key in context.budgeted_category_months:
            continue

        severity = _resolve_severity(rule, expense_snapshot.spent)
        if severity is None:
            continue

        scope_key = _category_month_scope_key(expense_snapshot.category_id, expense_snapshot.month)
        candidates.append(
            _candidate(
                rule,
                severity=severity,
                scope_key=scope_key,
                metadata={
                    "scope": rule.scope,
                    "scope_key": scope_key,
                    "category_id": expense_snapshot.category_id,
                    "category_name": expense_snapshot.category_name,
                    "spend_month": expense_snapshot.month.isoformat(),
                    "category_spend_amount": round(expense_snapshot.spent, 2),
                },
                format_context={
                    "category_name": expense_snapshot.category_name,
                    "budget_month_label": _month_label(expense_snapshot.month),
                    "category_spend_amount": _format_amount(expense_snapshot.spent, defaults),
                },
            )
        )
    return candidates


def _evaluate_consecutive_budget_overspend(
    rule: RuleConfig,
    context: InsightCalculationContext,
    defaults: dict[str, Any],
) -> list[InsightCandidate]:
    candidates: list[InsightCandidate] = []
    for budget in context.current_budgets:
        overspend_count = int(context.consecutive_overspend_counts.get((budget.category_id, budget.month), 0))
        if overspend_count <= 0:
            continue

        severity = _resolve_severity(rule, overspend_count)
        if severity is None:
            continue

        scope_key = _category_month_scope_key(budget.category_id, budget.month)
        candidates.append(
            _candidate(
                rule,
                severity=severity,
                scope_key=scope_key,
                metadata={
                    "scope": rule.scope,
                    "scope_key": scope_key,
                    "category_id": budget.category_id,
                    "category_name": budget.category_name,
                    "budget_month": budget.month.isoformat(),
                    "consecutive_overspend_count": overspend_count,
                    "budget_amount": round(budget.amount, 2),
                    "budget_spent": round(budget.spent, 2),
                },
                format_context={
                    "category_name": budget.category_name,
                    "budget_month_label": _month_label(budget.month),
                    "consecutive_overspend_count": overspend_count,
                    "budget_amount": _format_amount(budget.amount, defaults),
                    "budget_spent_amount": _format_amount(budget.spent, defaults),
                },
            )
        )
    return candidates


def _evaluate_negative_balance(
    rule: RuleConfig,
    context: InsightCalculationContext,
    defaults: dict[str, Any],
) -> list[InsightCandidate]:
    balance = context.current.balance
    severity = _resolve_less_than_severity(rule, balance)
    if severity is None:
        return []

    deficit_amount = abs(balance)
    return [
        _candidate(
            rule,
            severity=severity,
            metadata={
                "scope": rule.scope,
                "scope_key": "period",
                "balance_amount": round(balance, 2),
                "deficit_amount": round(deficit_amount, 2),
                "current_income": round(context.current.total_income, 2),
                "current_expense": round(context.current.total_expense, 2),
            },
            format_context={
                "balance_amount": _format_amount(balance, defaults),
                "deficit_amount": _format_amount(deficit_amount, defaults),
                "current_income_amount": _format_amount(context.current.total_income, defaults),
                "current_expense_amount": _format_amount(context.current.total_expense, defaults),
            },
        )
    ]


def _evaluate_negative_balance_below(
    rule: RuleConfig,
    context: InsightCalculationContext,
    defaults: dict[str, Any],
) -> list[InsightCandidate]:
    balance = context.current.balance
    severity = _resolve_less_than_or_equal_severity(rule, balance)
    if severity is None:
        return []

    deficit_amount = abs(balance)
    return [
        _candidate(
            rule,
            severity=severity,
            metadata={
                "scope": rule.scope,
                "scope_key": "period",
                "balance_amount": round(balance, 2),
                "deficit_amount": round(deficit_amount, 2),
                "current_income": round(context.current.total_income, 2),
                "current_expense": round(context.current.total_expense, 2),
            },
            format_context={
                "balance_amount": _format_amount(balance, defaults),
                "deficit_amount": _format_amount(deficit_amount, defaults),
                "current_income_amount": _format_amount(context.current.total_income, defaults),
                "current_expense_amount": _format_amount(context.current.total_expense, defaults),
            },
        )
    ]


def _evaluate_zero_income_with_expense(
    rule: RuleConfig,
    context: InsightCalculationContext,
    defaults: dict[str, Any],
) -> list[InsightCandidate]:
    if not context.current_period.is_full_month_span:
        return []

    min_income = float(defaults.get("min_income_for_ratio_rules", 0.0) or 0.0)
    if context.current.total_income > min_income or context.current.total_expense <= 0:
        return []

    severity = _select_highest_available_severity(rule, preferred="critical")

    return [
        _candidate(
            rule,
            severity=severity,
            metadata={
                "scope": rule.scope,
                "scope_key": "period",
                "current_income": round(context.current.total_income, 2),
                "current_expense": round(context.current.total_expense, 2),
                "zero_income": True,
            },
            format_context={
                "total_income_amount": _format_amount(context.current.total_income, defaults),
                "total_expense_amount": _format_amount(context.current.total_expense, defaults),
            },
            default_message=(
                f"You recorded { _format_amount(context.current.total_expense, defaults) } in expenses "
                "during the selected period but no income."
            ),
        )
    ]


def _candidate(
    rule: RuleConfig,
    *,
    severity: str,
    metadata: dict[str, Any],
    format_context: dict[str, Any],
    scope_key: str = "period",
    default_message: str | None = None,
) -> InsightCandidate:
    title = rule.titles.get(severity) or rule.settings.get("title") or rule.rule_id.replace("_", " ").title()
    if default_message is not None:
        message = default_message
    else:
        template = rule.message_templates.get(severity) or rule.message_template
        if template:
            try:
                message = template.format(**format_context)
            except KeyError:
                message = template
        else:
            message = title
    return InsightCandidate(
        rule_id=rule.rule_id,
        severity=severity,
        title=title,
        message=message,
        metadata=metadata,
        scope_key=scope_key,
    )


def _resolve_severity(rule: RuleConfig, measurement: float) -> str | None:
    triggered = [
        severity
        for severity, threshold in rule.severity_thresholds.items()
        if measurement >= float(threshold)
    ]
    if not triggered:
        return None
    return max(triggered, key=lambda severity: SEVERITY_ORDER[severity])


def _resolve_less_than_severity(rule: RuleConfig, measurement: float) -> str | None:
    triggered = [
        severity
        for severity, threshold in rule.severity_thresholds.items()
        if measurement < float(threshold)
    ]
    if not triggered:
        return None
    return max(triggered, key=lambda severity: SEVERITY_ORDER[severity])


def _resolve_less_than_or_equal_severity(rule: RuleConfig, measurement: float) -> str | None:
    triggered = [
        severity
        for severity, threshold in rule.severity_thresholds.items()
        if measurement <= float(threshold)
    ]
    if not triggered:
        return None
    return max(triggered, key=lambda severity: SEVERITY_ORDER[severity])


def _select_highest_available_severity(rule: RuleConfig, *, preferred: str) -> str:
    if preferred in rule.severity_thresholds:
        return preferred
    if rule.severity_thresholds:
        return max(rule.severity_thresholds.keys(), key=lambda severity: SEVERITY_ORDER[severity])
    return preferred


def _iter_current_expense_categories(period: PeriodMetrics) -> list[CategoryTotals]:
    return sorted(
        [category for category in period.category_totals.values() if category.expense_total > 0],
        key=lambda item: (-item.expense_total, item.category_name.lower()),
    )


def _category_allowed(rule: RuleConfig, category: CategoryTotals) -> bool:
    if not rule.category_names:
        return True
    return category.category_name.strip().lower() in set(rule.category_names)


def _category_scope_key(category_id: int) -> str:
    return f"category:{category_id}"


def _category_month_scope_key(category_id: int, month: Any) -> str:
    return f"category:{category_id}:month:{month.isoformat()}"


def _format_ratio_percent(value: float) -> str:
    return f"{value * 100:.1f}%"


def _format_percent(value: float) -> str:
    return f"{value:.1f}%"


def _format_amount(value: float, defaults: dict[str, Any]) -> str:
    currency = str(defaults.get("currency") or "").strip()
    prefix = f"{currency} " if currency else ""
    return f"{prefix}{value:,.2f}"


def _month_label(value: Any) -> str:
    return value.strftime("%B %Y")


def _validate_raw_rules_config(raw_config: dict[str, Any]) -> None:
    if not isinstance(raw_config, dict):
        raise ValueError("rules.yaml must contain a top-level mapping")

    raw_rules = raw_config.get("rules")
    if not isinstance(raw_rules, list):
        raise ValueError("rules.yaml must define a 'rules' list")

    seen_rule_ids: set[str] = set()
    for index, raw_rule in enumerate(raw_rules, start=1):
        if not isinstance(raw_rule, dict):
            raise ValueError(f"Rule #{index} must be a mapping")

        rule_id = str(raw_rule.get("id") or "").strip()
        if not rule_id:
            raise ValueError(f"Rule #{index} is missing a non-empty 'id'")
        if rule_id in seen_rule_ids:
            raise ValueError(f"Duplicate rule id '{rule_id}' found in rules.yaml")
        seen_rule_ids.add(rule_id)

        canonical_type = _canonical_rule_type(raw_rule.get("type"))
        if canonical_type not in SUPPORTED_RULE_TYPES:
            raise ValueError(f"Unknown rule type '{raw_rule.get('type')}' for rule '{rule_id}'")

        scope = str(raw_rule.get("scope") or _default_scope(canonical_type)).strip().lower()
        if scope not in SUPPORTED_SCOPES:
            raise ValueError(
                f"Rule '{rule_id}' uses unsupported scope '{raw_rule.get('scope') or scope}'"
            )

        severity_thresholds = raw_rule.get("severity_thresholds")
        if severity_thresholds is not None:
            if not isinstance(severity_thresholds, dict) or not severity_thresholds:
                raise ValueError(f"Rule '{rule_id}' must define a non-empty severity_thresholds mapping")
            for severity, threshold in severity_thresholds.items():
                _validate_severity_name(rule_id, severity)
                _validate_numeric_threshold(rule_id, severity, threshold)
        else:
            severity = raw_rule.get("severity")
            threshold = raw_rule.get("threshold")
            if severity is None or threshold is None:
                raise ValueError(
                    f"Rule '{rule_id}' must define either severity_thresholds or both severity and threshold"
                )
            _validate_severity_name(rule_id, severity)
            _validate_numeric_threshold(rule_id, str(severity), threshold)

        titles = raw_rule.get("titles")
        if titles is not None:
            if not isinstance(titles, dict):
                raise ValueError(f"Rule '{rule_id}' titles must be a mapping")
            for severity in titles:
                _validate_severity_name(rule_id, severity)

        message_templates = raw_rule.get("message_templates")
        if message_templates is not None:
            if not isinstance(message_templates, dict):
                raise ValueError(f"Rule '{rule_id}' message_templates must be a mapping")
            for severity in message_templates:
                _validate_severity_name(rule_id, severity)


def _validate_severity_name(rule_id: str, severity: Any) -> None:
    normalized = str(severity).lower()
    if normalized not in SEVERITY_ORDER:
        raise ValueError(f"Rule '{rule_id}' uses unsupported severity '{severity}'")


def _validate_numeric_threshold(rule_id: str, severity: str, threshold: Any) -> None:
    if isinstance(threshold, bool) or not isinstance(threshold, Number):
        raise ValueError(
            f"Rule '{rule_id}' threshold for severity '{severity}' must be numeric, got {threshold!r}"
        )


RULE_EVALUATORS: dict[str, Callable[[RuleConfig, InsightCalculationContext, dict[str, Any]], list[InsightCandidate]]] = {
    "expense_ratio": _evaluate_expense_ratio,
    "profit_drop_percent": _evaluate_profit_drop_percent,
    "spending_spike_percent": _evaluate_spending_spike_percent,
    "budget_overspend_ratio": _evaluate_budget_overspend_ratio,
    "category_income_ratio": _evaluate_category_income_ratio,
    "income_drop_percent": _evaluate_income_drop_percent,
    "missing_budget_high_spend": _evaluate_missing_budget_high_spend,
    "consecutive_budget_overspend": _evaluate_consecutive_budget_overspend,
    "negative_balance": _evaluate_negative_balance,
    "negative_balance_below": _evaluate_negative_balance_below,
    "zero_income_with_expense": _evaluate_zero_income_with_expense,
}
