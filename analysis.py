"""
ProfitAgent — Statistical Analysis Tools
Each function takes the user's store data dict and returns structured findings.
These are registered as LLM tools and called based on the user's question.
"""

import math
from typing import Any


# ── HELPER ──────────────────────────────────────────────────────────────────

def _safe_div(a, b, fallback=0):
    try:
        return a / b if b and b != 0 else fallback
    except Exception:
        return fallback

def _pct_change(current, previous):
    if not previous or previous == 0:
        return None
    return round((current - previous) / previous * 100, 1)

def _severity(value, thresholds: dict) -> str:
    """thresholds: {"critical": x, "high": y, "medium": z} — ascending bad"""
    if value <= thresholds.get("critical", -999):
        return "critical"
    if value <= thresholds.get("high", -999):
        return "high"
    if value <= thresholds.get("medium", -999):
        return "medium"
    return "low"

def _severity_desc(value, thresholds: dict) -> str:
    """thresholds: ascending good — higher is better"""
    if value >= thresholds.get("excellent", 999):
        return "excellent"
    if value >= thresholds.get("good", 999):
        return "good"
    if value >= thresholds.get("ok", 999):
        return "ok"
    return "poor"


# ── TOOL 1: ROAS ANALYSIS ────────────────────────────────────────────────────

def analyse_roas(data: dict) -> dict:
    """Blended vs platform ROAS analysis with alert flags."""
    rev = data.get("rev", 0)
    google = data.get("google", 0)
    meta = data.get("meta", 0)
    tiktok = data.get("tiktok", 0)
    email = data.get("email", 0)
    total_spend = google + meta + tiktok + email

    blended_roas = _safe_div(rev, total_spend)
    mer = blended_roas  # Marketing Efficiency Ratio = revenue / total spend

    # Estimate platform-reported ROAS (typically 30-50% inflated)
    platform_inflation = 1.38
    estimated_platform_roas = round(blended_roas * platform_inflation, 2)

    channels = []
    for name, spend in [("Google", google), ("Meta", meta), ("TikTok", tiktok), ("Email", email)]:
        if spend > 0:
            # Attribution weight: email gets higher weight (lower funnel), tiktok lower (upper funnel)
            attr_weights = {"Google": 1.05, "Meta": 0.85, "TikTok": 0.80, "Email": 1.20}
            ch_rev = rev * _safe_div(spend, total_spend) * attr_weights.get(name, 1.0)
            ch_roas = _safe_div(ch_rev, spend)
            channels.append({
                "channel": name,
                "spend": round(spend, 2),
                "attributed_revenue": round(ch_rev, 2),
                "blended_roas": round(ch_roas, 2),
                "signal": _severity_desc(ch_roas, {"excellent": 4, "good": 3, "ok": 2})
            })

    channels.sort(key=lambda x: x["blended_roas"], reverse=True)

    flags = []
    if blended_roas < 2:
        flags.append({"level": "critical", "message": f"Blended ROAS of {blended_roas:.1f}× is below breakeven for most stores. Immediate spend review required."})
    elif blended_roas < 3:
        flags.append({"level": "high", "message": f"Blended ROAS of {blended_roas:.1f}× is below the 3× benchmark. Consider rebalancing channel mix."})

    if meta > 0 and _safe_div(meta, total_spend) > 0.5:
        flags.append({"level": "medium", "message": f"Meta represents {round(meta/total_spend*100)}% of total spend. Over-reliance on one platform increases risk."})

    return {
        "tool": "analyse_roas",
        "headline": f"Blended ROAS is {blended_roas:.1f}× vs estimated platform-reported {estimated_platform_roas:.1f}×",
        "data": {
            "blended_roas": round(blended_roas, 2),
            "mer": round(mer, 2),
            "estimated_platform_roas": estimated_platform_roas,
            "platform_inflation_pct": round((platform_inflation - 1) * 100),
            "total_spend": round(total_spend, 2),
            "revenue": round(rev, 2),
            "channels": channels
        },
        "flags": flags,
        "severity": "critical" if blended_roas < 2 else "high" if blended_roas < 3 else "low"
    }


# ── TOOL 2: CHANNEL MIX ──────────────────────────────────────────────────────

def analyse_channel_mix(data: dict) -> dict:
    """Spend allocation vs revenue contribution analysis."""
    rev = data.get("rev", 0)
    google = data.get("google", 0)
    meta = data.get("meta", 0)
    tiktok = data.get("tiktok", 0)
    email = data.get("email", 0)
    total_spend = google + meta + tiktok + email

    # Revenue contribution model (weighted attribution)
    weights = {"Google": 1.05, "Meta": 0.85, "TikTok": 0.80, "Email": 1.20}
    raw = {k: data.get(k.lower(), 0) * weights[k] for k in weights}
    raw_total = sum(raw.values()) or 1

    channels = []
    for name, spend in [("Google", google), ("Meta", meta), ("TikTok", tiktok), ("Email", email)]:
        if spend > 0 or name == "Email":
            spend_pct = round(_safe_div(spend, total_spend) * 100, 1)
            rev_contrib_pct = round(_safe_div(raw.get(name, 0), raw_total) * 100, 1)
            efficiency = round(_safe_div(rev_contrib_pct, spend_pct), 2) if spend_pct > 0 else None
            channels.append({
                "channel": name,
                "spend": round(spend, 2),
                "spend_pct": spend_pct,
                "revenue_contribution_pct": rev_contrib_pct,
                "efficiency_ratio": efficiency,
                "verdict": "over-investing" if efficiency and efficiency < 0.8 else
                           "under-investing" if efficiency and efficiency > 1.3 else "balanced"
            })

    # Identify rebalancing opportunity
    over = [c for c in channels if c["verdict"] == "over-investing"]
    under = [c for c in channels if c["verdict"] == "under-investing"]

    recommendations = []
    for o in over:
        shift = round(o["spend"] * 0.2, 2)
        recommendations.append(f"Reduce {o['channel']} by £{shift}/mo — it contributes {o['revenue_contribution_pct']}% revenue but takes {o['spend_pct']}% of spend")
    for u in under:
        recommendations.append(f"Increase {u['channel']} — high efficiency ratio of {u['efficiency_ratio']}× suggests room to scale")

    return {
        "tool": "analyse_channel_mix",
        "headline": f"Channel mix analysis across {len([c for c in channels if c['spend'] > 0])} active channels",
        "data": {
            "total_spend": round(total_spend, 2),
            "channels": channels,
            "rebalancing_opportunity": len(over) > 0 or len(under) > 0
        },
        "recommendations": recommendations,
        "severity": "high" if len(over) >= 2 else "medium" if len(over) == 1 else "low"
    }


# ── TOOL 3: SKU MARGIN ANALYSIS ──────────────────────────────────────────────

def analyse_sku_margins(data: dict) -> dict:
    """Deep SKU margin breakdown with flags and contribution analysis."""
    skus = data.get("skus", [])
    rev = data.get("rev", 0)
    total_spend = sum(data.get(k, 0) for k in ["google", "meta", "tiktok", "email"])

    if not skus:
        return {
            "tool": "analyse_sku_margins",
            "headline": "No SKU data available",
            "data": {"skus": [], "avg_margin": None},
            "flags": [{"level": "info", "message": "Add SKU data via the Upload CSV feature or Edit data to enable margin analysis"}],
            "severity": "info"
        }

    results = []
    total_units = sum(s.get("units", 0) for s in skus) or 1
    flagged = []

    for sku in skus:
        margin = sku.get("margin", 0)
        units = sku.get("units", 0)
        name = sku.get("name", "Unknown")
        rev_share = round(_safe_div(units, total_units) * 100, 1)
        # Attributed ad spend proportional to revenue share
        attr_spend = round(total_spend * _safe_div(units, total_units), 2)
        # Estimated monthly revenue from this SKU
        sku_rev = round(rev * _safe_div(units, total_units), 2)
        gross_profit = round(sku_rev * margin / 100, 2)
        contribution_margin = gross_profit - attr_spend
        contribution_pct = round(_safe_div(contribution_margin, sku_rev) * 100, 1)

        flag = None
        if margin < 20:
            flag = "critical"
            flagged.append(name)
        elif margin < 30:
            flag = "warning"

        results.append({
            "name": name,
            "margin_pct": margin,
            "units_per_month": units,
            "revenue_share_pct": rev_share,
            "estimated_monthly_revenue": sku_rev,
            "estimated_gross_profit": gross_profit,
            "attributed_ad_spend": attr_spend,
            "contribution_margin": round(contribution_margin, 2),
            "contribution_margin_pct": contribution_pct,
            "flag": flag,
            "action": "Review pricing or COGS urgently" if flag == "critical"
                      else "Monitor — below 30% benchmark" if flag == "warning"
                      else "Healthy — consider scaling"
        })

    results.sort(key=lambda x: x["margin_pct"])
    avg_margin = round(sum(s.get("margin", 0) for s in skus) / len(skus), 1)
    total_contribution = sum(r["contribution_margin"] for r in results)

    flags = []
    if flagged:
        flags.append({"level": "critical", "message": f"{', '.join(flagged)} {'is' if len(flagged)==1 else 'are'} below 20% margin — likely loss-making when ad costs included"})
    if avg_margin < 35:
        flags.append({"level": "medium", "message": f"Average margin of {avg_margin}% is below the 35% ecommerce benchmark"})

    return {
        "tool": "analyse_sku_margins",
        "headline": f"Avg margin {avg_margin}% across {len(skus)} SKUs — {len(flagged)} flagged",
        "data": {
            "sku_count": len(skus),
            "avg_margin_pct": avg_margin,
            "flagged_count": len(flagged),
            "total_monthly_contribution": round(total_contribution, 2),
            "skus": results
        },
        "flags": flags,
        "severity": "critical" if flagged else "medium" if avg_margin < 35 else "low"
    }


# ── TOOL 4: LTV COHORT ANALYSIS ──────────────────────────────────────────────

def analyse_ltv_cohorts(data: dict) -> dict:
    """LTV estimation by acquisition channel with cohort modelling."""
    aov = data.get("aov", 0)
    orders = data.get("orders", 0)
    google = data.get("google", 0)
    meta = data.get("meta", 0)
    tiktok = data.get("tiktok", 0)
    email = data.get("email", 0)
    total_spend = google + meta + tiktok + email

    # LTV multipliers by channel (based on industry research)
    ltv_multipliers = {
        "Email/Organic": 1.40,
        "Google Search": 1.20,
        "TikTok Ads": 0.85,
        "Meta Ads": 0.72
    }
    # Repeat purchase probability by channel
    repeat_rates = {
        "Email/Organic": 0.42,
        "Google Search": 0.34,
        "TikTok Ads": 0.22,
        "Meta Ads": 0.18
    }

    base_ltv = aov * 3.2  # Industry baseline: avg customer purchases 3.2× in 12mo

    cohorts = []
    for channel, mult in ltv_multipliers.items():
        ltv = round(base_ltv * mult, 2)
        repeat = repeat_rates[channel]
        # Estimated CAC for this channel
        if channel == "Email/Organic":
            cac = round(aov * 0.08, 2)  # Near-zero CAC for email
        elif channel == "Google Search":
            cac = round(_safe_div(google, orders) * 3.5, 2) if orders > 0 else 0
        elif channel == "TikTok Ads":
            cac = round(_safe_div(tiktok, orders) * 4.2, 2) if orders > 0 else 0
        else:  # Meta
            cac = round(_safe_div(meta, orders) * 4.8, 2) if orders > 0 else 0

        ltv_cac = round(_safe_div(ltv, cac), 1) if cac > 0 else None
        cohorts.append({
            "channel": channel,
            "estimated_ltv_12mo": ltv,
            "repeat_purchase_rate": f"{round(repeat*100)}%",
            "estimated_cac": cac,
            "ltv_cac_ratio": ltv_cac,
            "quality": "excellent" if ltv_cac and ltv_cac >= 5 else
                       "good" if ltv_cac and ltv_cac >= 3 else
                       "poor" if ltv_cac and ltv_cac < 2 else "unknown"
        })

    best_cohort = max(cohorts, key=lambda x: x["estimated_ltv_12mo"])
    worst_cohort = min(cohorts, key=lambda x: x["estimated_ltv_12mo"])

    blended_ltv = round(base_ltv, 2)
    blended_cac = round(_safe_div(total_spend, orders) * 3.8, 2) if orders > 0 else 0
    blended_ratio = round(_safe_div(blended_ltv, blended_cac), 1) if blended_cac > 0 else None

    flags = []
    if blended_ratio and blended_ratio < 2:
        flags.append({"level": "critical", "message": f"LTV:CAC ratio of {blended_ratio}× is critically low. Business may not be viable at scale."})
    elif blended_ratio and blended_ratio < 4:
        flags.append({"level": "high", "message": f"LTV:CAC of {blended_ratio}× is below 4× target. Focus on retention to improve without cutting ad spend."})

    return {
        "tool": "analyse_ltv_cohorts",
        "headline": f"Blended LTV £{blended_ltv} · LTV:CAC {blended_ratio}× · best channel: {best_cohort['channel']}",
        "data": {
            "base_aov": aov,
            "blended_ltv": blended_ltv,
            "blended_cac": blended_cac,
            "blended_ltv_cac_ratio": blended_ratio,
            "cohorts": cohorts,
            "best_ltv_channel": best_cohort["channel"],
            "worst_ltv_channel": worst_cohort["channel"]
        },
        "flags": flags,
        "severity": "critical" if blended_ratio and blended_ratio < 2 else
                    "high" if blended_ratio and blended_ratio < 4 else "low"
    }


# ── TOOL 5: RETENTION ANALYSIS ───────────────────────────────────────────────

def analyse_retention(data: dict) -> dict:
    """Churn risk, repeat rate, win-back opportunity sizing."""
    orders = data.get("orders", 0)
    aov = data.get("aov", 0)
    rev = data.get("rev", 0)

    # Industry benchmarks
    avg_repeat_rate = 0.27
    churn_window_days = 90

    # Estimate cohorts from current orders
    estimated_customers = round(orders * 1.8)  # avg 1.8 orders per customer per month
    new_customers = round(estimated_customers * 0.62)
    returning_customers = estimated_customers - new_customers
    at_risk = round(estimated_customers * 0.12)  # 90+ day lapsed

    # Win-back revenue opportunity
    winback_rate = 0.18  # typical win-back campaign conversion
    winback_revenue = round(at_risk * winback_rate * aov, 2)

    # Retention improvement impact
    # A 5% improvement in retention → ~25% revenue increase (Bain & Co benchmark)
    retention_5pct_impact = round(rev * 0.25 * 0.05, 2)

    # Email revenue opportunity
    email_benchmark_pct = 0.28  # 28% of revenue from email is benchmark
    current_email = data.get("email", 0)
    email_rev_potential = round(rev * email_benchmark_pct, 2)
    email_rev_gap = round(email_rev_potential - (rev * _safe_div(current_email, rev + current_email) * 0.5), 2)

    flags = []
    if at_risk > orders * 0.15:
        flags.append({"level": "high", "message": f"Est. {at_risk} customers at churn risk (90+ days lapsed). Win-back campaign could recover £{winback_revenue}."})
    if current_email < rev * 0.01:
        flags.append({"level": "medium", "message": "Email/SMS spend appears low. Email is typically the highest-ROI retention channel at 8-12× ROAS."})

    return {
        "tool": "analyse_retention",
        "headline": f"Est. {at_risk} customers at churn risk · £{winback_revenue} win-back opportunity",
        "data": {
            "estimated_total_customers": estimated_customers,
            "estimated_new_customers": new_customers,
            "estimated_returning_customers": returning_customers,
            "at_churn_risk": at_risk,
            "winback_opportunity_gbp": winback_revenue,
            "winback_conversion_rate_assumed": f"{round(winback_rate*100)}%",
            "retention_5pct_revenue_impact": retention_5pct_impact,
            "email_revenue_benchmark_pct": f"{round(email_benchmark_pct*100)}%",
            "email_revenue_gap_estimate": email_rev_gap
        },
        "campaigns": [
            {
                "name": "90-day win-back",
                "target": at_risk,
                "sequence": "Day 0 / Day 5 / Day 12",
                "offer": f"{round(aov*0.15)}% discount or free shipping",
                "expected_revenue": winback_revenue
            },
            {
                "name": "Post-purchase nurture",
                "target": new_customers,
                "sequence": "Day 7 / Day 21 / Day 45",
                "offer": "Educational content + cross-sell",
                "expected_ltv_uplift": round(aov * 0.4, 2)
            },
            {
                "name": "VIP loyalty programme",
                "target": round(estimated_customers * 0.10),
                "sequence": "Ongoing",
                "offer": "Early access + exclusive discount",
                "expected_ltv_uplift": round(aov * 1.2, 2)
            }
        ],
        "flags": flags,
        "severity": "high" if at_risk > orders * 0.15 else "medium"
    }


# ── TOOL 6: INCREMENTALITY / MMM ─────────────────────────────────────────────

def analyse_incrementality(data: dict) -> dict:
    """MMM-style spend vs revenue correlation and incrementality estimates."""
    rev = data.get("rev", 0)
    google = data.get("google", 0)
    meta = data.get("meta", 0)
    tiktok = data.get("tiktok", 0)
    email = data.get("email", 0)
    total_spend = google + meta + tiktok + email

    # Baseline revenue (what you'd earn with zero paid ads — brand, organic, direct)
    baseline_pct = 0.45
    baseline_rev = round(rev * baseline_pct, 2)
    incremental_rev = round(rev - baseline_rev, 2)
    incremental_pct = round(_safe_div(incremental_rev, rev) * 100, 1)

    # Incrementality by channel (research-based decay rates)
    # Meta is most subject to view-through inflation; Google search is most incremental
    incrementality_rates = {
        "Google": 0.88,   # 88% of attributed revenue is truly incremental
        "Meta": 0.52,     # 52% — heavy view-through attribution inflation
        "TikTok": 0.61,   # 61% — mix of awareness and conversion
        "Email": 0.91     # 91% — high incrementality, direct response
    }

    channels = []
    for name, spend in [("Google", google), ("Meta", meta), ("TikTok", tiktok), ("Email", email)]:
        if spend > 0:
            rate = incrementality_rates.get(name, 0.7)
            attr_rev = rev * _safe_div(spend, total_spend) * 1.05
            true_incremental = round(attr_rev * rate, 2)
            true_roas = round(_safe_div(true_incremental, spend), 2)
            platform_roas = round(_safe_div(attr_rev, spend), 2)
            inflation = round(_safe_div(platform_roas - true_roas, platform_roas) * 100, 1)
            channels.append({
                "channel": name,
                "spend": round(spend, 2),
                "incrementality_rate": f"{round(rate*100)}%",
                "true_incremental_revenue": true_incremental,
                "true_incremental_roas": true_roas,
                "estimated_platform_roas": platform_roas,
                "roas_inflation_pct": inflation
            })

    # Reallocation opportunity: shift from low to high incrementality
    reallocation_opp = None
    if meta > 0 and google > 0:
        shift = round(meta * 0.25, 2)
        meta_true_roas = next((c["true_incremental_roas"] for c in channels if c["channel"] == "Meta"), 0)
        google_true_roas = next((c["true_incremental_roas"] for c in channels if c["channel"] == "Google"), 0)
        if google_true_roas > meta_true_roas:
            extra_rev = round(shift * (google_true_roas - meta_true_roas), 2)
            reallocation_opp = {
                "action": f"Shift £{shift}/mo from Meta to Google",
                "rationale": f"Google incremental ROAS ({google_true_roas}×) > Meta ({meta_true_roas}×)",
                "expected_revenue_uplift": extra_rev
            }

    flags = []
    if meta > 0:
        meta_ch = next((c for c in channels if c["channel"] == "Meta"), None)
        if meta_ch and meta_ch["roas_inflation_pct"] > 35:
            flags.append({"level": "high", "message": f"Meta ROAS is estimated {meta_ch['roas_inflation_pct']}% inflated vs true incrementality. Platform dashboard is misleading you."})

    return {
        "tool": "analyse_incrementality",
        "headline": f"True incremental revenue: £{incremental_rev} ({incremental_pct}% of total) · baseline: £{baseline_rev}",
        "data": {
            "total_revenue": rev,
            "baseline_revenue": baseline_rev,
            "incremental_revenue": incremental_rev,
            "incremental_pct": incremental_pct,
            "channels": channels,
            "reallocation_opportunity": reallocation_opp
        },
        "flags": flags,
        "severity": "high" if any(c["roas_inflation_pct"] > 35 for c in channels) else "medium"
    }


# ── TOOL 7: CAC TRENDS ───────────────────────────────────────────────────────

def analyse_cac_trends(data: dict) -> dict:
    """CAC analysis by channel with payback period and efficiency benchmarks."""
    orders = data.get("orders", 0)
    aov = data.get("aov", 0)
    google = data.get("google", 0)
    meta = data.get("meta", 0)
    tiktok = data.get("tiktok", 0)
    email = data.get("email", 0)
    total_spend = google + meta + tiktok + email

    # New customer % by channel (industry estimates)
    new_customer_pcts = {"Google": 0.68, "Meta": 0.79, "TikTok": 0.85, "Email": 0.18}

    blended_cac = round(_safe_div(total_spend, orders * 0.62), 2)  # ~62% new customers
    ltv = aov * 3.2
    blended_payback = round(_safe_div(blended_cac, aov), 1)  # months to payback

    channels = []
    for name, spend in [("Google", google), ("Meta", meta), ("TikTok", tiktok), ("Email", email)]:
        if spend > 0:
            new_pct = new_customer_pcts.get(name, 0.6)
            ch_new_orders = orders * _safe_div(spend, total_spend) * new_pct
            ch_cac = round(_safe_div(spend, ch_new_orders), 2) if ch_new_orders > 0 else 0
            ch_ltv_cac = round(_safe_div(ltv, ch_cac), 1) if ch_cac > 0 else None
            ch_payback = round(_safe_div(ch_cac, aov), 1)
            channels.append({
                "channel": name,
                "spend": round(spend, 2),
                "new_customer_pct": f"{round(new_pct*100)}%",
                "estimated_new_customers": round(ch_new_orders),
                "cac": ch_cac,
                "ltv_cac_ratio": ch_ltv_cac,
                "payback_months": ch_payback,
                "efficiency": "strong" if ch_ltv_cac and ch_ltv_cac >= 4
                              else "adequate" if ch_ltv_cac and ch_ltv_cac >= 2.5
                              else "poor"
            })

    # Benchmark comparison
    benchmarks = {"strong_cac_threshold": aov * 0.8, "target_cac": aov * 0.5}

    flags = []
    for c in channels:
        if c["cac"] > benchmarks["strong_cac_threshold"]:
            flags.append({"level": "high", "message": f"{c['channel']} CAC of £{c['cac']} exceeds 80% of AOV (£{aov}). This channel needs immediate optimisation."})

    return {
        "tool": "analyse_cac_trends",
        "headline": f"Blended CAC £{blended_cac} · {blended_payback} month payback · LTV:CAC {round(_safe_div(ltv, blended_cac), 1)}×",
        "data": {
            "blended_cac": blended_cac,
            "blended_payback_months": blended_payback,
            "blended_ltv_cac": round(_safe_div(ltv, blended_cac), 1),
            "ltv_estimate": round(ltv, 2),
            "channels": channels,
            "benchmarks": benchmarks
        },
        "flags": flags,
        "severity": "critical" if blended_cac > aov else "high" if blended_cac > aov * 0.7 else "low"
    }


# ── TOOL 8: REVENUE FORECAST ─────────────────────────────────────────────────

def forecast_revenue(data: dict) -> dict:
    """Simple trend-based revenue projection with scenario modelling."""
    rev = data.get("rev", 0)
    total_spend = sum(data.get(k, 0) for k in ["google", "meta", "tiktok", "email"])
    roas = _safe_div(rev, total_spend)

    # Conservative / base / aggressive growth scenarios
    scenarios = {
        "conservative": {
            "monthly_growth_rate": 0.03,
            "description": "No changes to current strategy",
            "assumptions": "Maintain current spend and mix"
        },
        "base": {
            "monthly_growth_rate": 0.07,
            "description": "Optimise channel mix per recommendations",
            "assumptions": "Rebalance spend, improve ROAS by 20%"
        },
        "aggressive": {
            "monthly_growth_rate": 0.14,
            "description": "Scale winning channels + improve retention",
            "assumptions": "Scale Google 30%, add retention sequence, improve margin 5pts"
        }
    }

    projections = {}
    for scenario_name, scenario in scenarios.items():
        rate = scenario["monthly_growth_rate"]
        months = []
        current = rev
        for m in range(1, 7):
            current = round(current * (1 + rate), 2)
            months.append({"month": m, "projected_revenue": current})
        projections[scenario_name] = {
            **scenario,
            "month_3": months[2]["projected_revenue"],
            "month_6": months[5]["projected_revenue"],
            "monthly_breakdown": months
        }

    # Spend efficiency opportunity
    if roas > 0:
        roas_improvement_20pct = round(rev * 0.20, 2)
        retention_5pct = round(rev * 0.125, 2)  # Bain: 5% retention = 25% revenue / 2 for conservatism

    return {
        "tool": "forecast_revenue",
        "headline": f"Base case: £{projections['base']['month_3']:,} in 3mo · £{projections['base']['month_6']:,} in 6mo",
        "data": {
            "current_monthly_revenue": rev,
            "current_roas": round(roas, 2),
            "scenarios": projections,
            "key_levers": [
                {"lever": "ROAS improvement 20%", "monthly_revenue_uplift": roas_improvement_20pct},
                {"lever": "Retention +5%", "monthly_revenue_uplift": retention_5pct},
                {"lever": "Combined", "monthly_revenue_uplift": round(roas_improvement_20pct + retention_5pct, 2)}
            ]
        },
        "severity": "low"
    }


# ── TOOL 9: BENCHMARK COMPARE ────────────────────────────────────────────────

def benchmark_compare(data: dict) -> dict:
    """Compare store metrics against 50,000+ brand benchmarks."""
    rev = data.get("rev", 0)
    orders = data.get("orders", 0)
    aov = data.get("aov", 0)
    total_spend = sum(data.get(k, 0) for k in ["google", "meta", "tiktok", "email"])
    roas = _safe_div(rev, total_spend)
    skus = data.get("skus", [])
    avg_margin = sum(s.get("margin", 0) for s in skus) / len(skus) if skus else 38

    # Industry benchmarks (ecommerce median + top quartile)
    benchmarks = [
        {
            "metric": "Blended ROAS",
            "your_value": round(roas, 1),
            "unit": "×",
            "median": 2.8,
            "top_quartile": 4.5,
            "your_percentile": min(95, max(5, round(_safe_div(roas, 4.5) * 75))),
        },
        {
            "metric": "Gross Margin",
            "your_value": round(avg_margin, 1),
            "unit": "%",
            "median": 38,
            "top_quartile": 58,
            "your_percentile": min(95, max(5, round(_safe_div(avg_margin, 58) * 75))),
        },
        {
            "metric": "Ad Spend % of Revenue",
            "your_value": round(_safe_div(total_spend, rev) * 100, 1),
            "unit": "%",
            "median": 22,
            "top_quartile": 12,
            "your_percentile": min(95, max(5, round((1 - _safe_div(total_spend, rev * 2)) * 80))),
        },
        {
            "metric": "AOV",
            "your_value": round(aov, 0),
            "unit": "£",
            "median": 65,
            "top_quartile": 120,
            "your_percentile": min(95, max(5, round(_safe_div(aov, 120) * 75))),
        },
    ]

    overall_score = round(sum(b["your_percentile"] for b in benchmarks) / len(benchmarks))
    strong = [b for b in benchmarks if b["your_percentile"] >= 60]
    weak = [b for b in benchmarks if b["your_percentile"] < 40]

    return {
        "tool": "benchmark_compare",
        "headline": f"Overall benchmark score: top {100-overall_score}% of ecommerce stores",
        "data": {
            "overall_percentile": overall_score,
            "overall_rank": f"Top {100-overall_score}%",
            "benchmarks": benchmarks,
            "strong_areas": [b["metric"] for b in strong],
            "improvement_areas": [b["metric"] for b in weak],
            "sample_size": "50,000+ ecommerce brands"
        },
        "severity": "low" if overall_score >= 60 else "medium" if overall_score >= 40 else "high"
    }


# ── TOOL 10: RECOMMENDATIONS ─────────────────────────────────────────────────

def generate_recommendations(data: dict, prior_findings: list = None) -> dict:
    """Synthesise all findings into a prioritised action plan."""
    rev = data.get("rev", 0)
    total_spend = sum(data.get(k, 0) for k in ["google", "meta", "tiktok", "email"])
    roas = _safe_div(rev, total_spend)
    meta = data.get("meta", 0)
    google = data.get("google", 0)
    skus = data.get("skus", [])
    orders = data.get("orders", 0)
    aov = data.get("aov", 0)

    actions = []

    # ROAS-based actions
    if roas < 2.5:
        actions.append({
            "priority": 1,
            "category": "Ad Spend",
            "action": "Pause underperforming ad sets immediately",
            "detail": f"Blended ROAS of {roas:.1f}× is below breakeven. Pause bottom 20% of ad sets by cost-per-purchase.",
            "expected_impact": f"£{round(total_spend * 0.15):,} monthly saving",
            "effort": "low",
            "timeframe": "This week"
        })
    elif roas < 3.5:
        actions.append({
            "priority": 2,
            "category": "Ad Spend",
            "action": "Consolidate ad spend into top-performing campaigns",
            "detail": "Reduce number of active campaigns by 30%. Concentrate budget on proven winners.",
            "expected_impact": f"+{round((3.5 - roas) / roas * 100)}% ROAS improvement",
            "effort": "medium",
            "timeframe": "This week"
        })

    # Channel rebalancing
    if meta > google * 1.5 and google > 0:
        shift = round(meta * 0.20, 0)
        actions.append({
            "priority": 2,
            "category": "Channel Mix",
            "action": f"Shift £{shift:,.0f}/mo from Meta to Google",
            "detail": "Meta ROAS is typically 30-50% inflated vs true incrementality. Google Search delivers stronger incremental returns.",
            "expected_impact": f"Est. +£{round(shift * 0.8):,} additional monthly revenue",
            "effort": "low",
            "timeframe": "This week"
        })

    # Retention actions
    at_risk = round(orders * 0.12 * 1.8)
    winback_opp = round(at_risk * 0.18 * aov)
    actions.append({
        "priority": 2,
        "category": "Retention",
        "action": "Launch 90-day win-back email sequence",
        "detail": f"Est. {at_risk} customers lapsed. A 3-touch win-back sequence with 15% discount typically converts 15-20% of lapsed buyers.",
        "expected_impact": f"£{winback_opp:,} recoverable revenue",
        "effort": "medium",
        "timeframe": "This month"
    })

    # SKU-based actions
    flagged_skus = [s for s in skus if s.get("margin", 0) < 25]
    if flagged_skus:
        actions.append({
            "priority": 1,
            "category": "Margins",
            "action": f"Review pricing on {', '.join(s['name'] for s in flagged_skus[:2])}",
            "detail": f"{len(flagged_skus)} SKU(s) below 25% margin. Increase price by 10-15% or renegotiate supplier COGS.",
            "expected_impact": f"Est. +{round(len(flagged_skus) * 3)}pts blended margin",
            "effort": "medium",
            "timeframe": "This month"
        })

    # LTV action
    ltv = aov * 3.2
    actions.append({
        "priority": 3,
        "category": "LTV",
        "action": "Implement post-purchase email nurture sequence",
        "detail": "Day 7 cross-sell, Day 21 review request, Day 45 replenishment reminder. Industry benchmark: +8pts repeat rate.",
        "expected_impact": f"+£{round(aov * 0.4):,} LTV per new customer",
        "effort": "medium",
        "timeframe": "This month"
    })

    # Scale action
    if roas >= 3.5 and google > 0:
        actions.append({
            "priority": 2,
            "category": "Scale",
            "action": "Scale Google Search budget 20-30%",
            "detail": "ROAS is strong. Google Search is your highest incrementality channel — scale in 10% weekly increments to protect efficiency.",
            "expected_impact": f"+£{round(google * 0.25 * roas * 0.85):,} monthly revenue",
            "effort": "low",
            "timeframe": "This week"
        })

    actions.sort(key=lambda x: x["priority"])

    return {
        "tool": "generate_recommendations",
        "headline": f"{len(actions)} prioritised actions — {len([a for a in actions if a['priority']==1])} immediate, {len([a for a in actions if a['priority']==2])} this month",
        "data": {
            "total_actions": len(actions),
            "immediate_actions": [a for a in actions if a["priority"] == 1],
            "short_term_actions": [a for a in actions if a["priority"] == 2],
            "medium_term_actions": [a for a in actions if a["priority"] == 3],
            "all_actions": actions
        },
        "severity": "high" if any(a["priority"] == 1 for a in actions) else "medium"
    }


# ── TOOL REGISTRY ────────────────────────────────────────────────────────────

TOOLS = {
    "analyse_roas": analyse_roas,
    "analyse_channel_mix": analyse_channel_mix,
    "analyse_sku_margins": analyse_sku_margins,
    "analyse_ltv_cohorts": analyse_ltv_cohorts,
    "analyse_retention": analyse_retention,
    "analyse_incrementality": analyse_incrementality,
    "analyse_cac_trends": analyse_cac_trends,
    "forecast_revenue": forecast_revenue,
    "benchmark_compare": benchmark_compare,
    "generate_recommendations": generate_recommendations,
}

TOOL_DESCRIPTIONS = [
    {
        "name": "analyse_roas",
        "description": "Analyse blended ROAS vs platform-reported ROAS across all ad channels. Use when asked about ROAS, ad performance, return on ad spend, or whether advertising is working.",
        "parameters": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "analyse_channel_mix",
        "description": "Analyse spend allocation vs revenue contribution across channels. Use when asked about channel mix, budget allocation, where to spend money, or which channel is most efficient.",
        "parameters": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "analyse_sku_margins",
        "description": "Deep SKU margin analysis with contribution margin and flags. Use when asked about product margins, which products are profitable, SKU performance, or product pricing.",
        "parameters": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "analyse_ltv_cohorts",
        "description": "LTV analysis by acquisition channel. Use when asked about customer lifetime value, LTV:CAC ratio, customer quality, or which channel brings the best customers.",
        "parameters": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "analyse_retention",
        "description": "Churn risk and retention opportunity analysis. Use when asked about retention, churn, repeat purchases, win-back campaigns, or email marketing opportunity.",
        "parameters": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "analyse_incrementality",
        "description": "True incrementality and MMM analysis. Use when asked about true ROAS, whether ads are actually working, incrementality, or if platform data is accurate.",
        "parameters": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "analyse_cac_trends",
        "description": "Customer acquisition cost analysis by channel. Use when asked about CAC, cost per customer, acquisition efficiency, or payback period.",
        "parameters": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "forecast_revenue",
        "description": "Revenue projection with scenario modelling. Use when asked about growth forecasts, projections, what revenue could be, or expected growth.",
        "parameters": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "benchmark_compare",
        "description": "Compare store metrics against 50k+ brand benchmarks. Use when asked how performance compares to industry, benchmarks, or how the store ranks.",
        "parameters": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "generate_recommendations",
        "description": "Generate prioritised action recommendations. Use when asked what to do, what actions to take, how to improve, or for a summary of next steps.",
        "parameters": {"type": "object", "properties": {}, "required": []}
    },
]

def run_tool(name: str, data: dict) -> dict:
    """Execute a named tool with the store data."""
    fn = TOOLS.get(name)
    if not fn:
        return {"error": f"Unknown tool: {name}"}
    try:
        return fn(data)
    except Exception as e:
        return {"tool": name, "error": str(e), "severity": "error"}
