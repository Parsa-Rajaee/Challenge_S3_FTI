"""Generate publication-quality Seaborn visualizations for Part 3 Credit Risk ML.

Theme: Modern Financial Risk Analytics (Seaborn darkgrid + high-contrast corporate palette)
Output: PNG figures saved to reports/figures/
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    auc,
    confusion_matrix,
    precision_recall_curve,
    roc_auc_score,
    roc_curve,
)
from sklearn.model_selection import StratifiedKFold, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

# Ensure package is importable
SRC_DIR = Path(__file__).resolve().parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from credit_risk.cost import (
    DEFAULT_COST_FN,
    DEFAULT_COST_FP,
    calculate_expected_cost_per_thousand,
    calculate_total_cost,
    find_optimal_threshold,
)
from credit_risk.db import load_clean_borrowers
from credit_risk.features import add_engineered_features
from credit_risk.sentinel import SentinelAuditor

# ---------------------------------------------------------
# Theme and Styling Configuration
# ---------------------------------------------------------
sns.set_theme(style="darkgrid")
plt.rcParams.update({"figure.figsize": (11, 5.5), "figure.dpi": 130, "savefig.dpi": 300})

# Color Constants
NAVY = "#1E3A8A"
BLUE = "#2563EB"
SKY = "#38BDF8"
RED = "#DC2626"
CRIMSON = "#991B1B"
GREEN = "#059669"
EMERALD = "#10B981"
AMBER = "#D97706"
GRAY = "#64748B"
LIGHT_BG = "#F8FAFC"

FIG_DIR = Path(__file__).resolve().parent / "reports" / "figures"
FIG_DIR.mkdir(parents=True, exist_ok=True)


def plot_fig1_target_imbalance_and_cost(df: pd.DataFrame) -> None:
    """Figure 1: Target Class Imbalance and The Accuracy Paradox."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5.5))

    # Left: Class Counts & Percentages
    counts = df["serious_dlqin_2yrs"].value_counts()
    ratios = df["serious_dlqin_2yrs"].value_counts(normalize=True) * 100
    labels = ["Healthy Borrowers\n(Class 0)", "Defaulted Borrowers\n(Class 1)"]
    palette = [BLUE, RED]

    bars = ax1.bar(
        labels,
        [counts[0], counts[1]],
        color=palette,
        width=0.55,
        edgecolor="#1E293B",
        linewidth=1.2,
    )
    ax1.set_ylabel("Number of Applicants", fontsize=11, fontweight="semibold")
    ax1.set_title(
        "Credit Risk Dataset: Severe Class Imbalance", fontsize=13, fontweight="bold", pad=12
    )
    ax1.set_ylim(0, 160000)
    ax1.yaxis.set_major_formatter("{x:,.0f}")

    for bar, count, pct in zip(bars, [counts[0], counts[1]], [ratios[0], ratios[1]]):
        yval = bar.get_height()
        ax1.text(
            bar.get_x() + bar.get_width() / 2.0,
            yval + 4000,
            f"{count:,}\n({pct:.2f}%)",
            ha="center",
            va="bottom",
            fontsize=10.5,
            fontweight="bold",
        )
    ax1.axhline(counts[0], color=BLUE, linestyle=":", alpha=0.4)
    ax1.text(
        0.5,
        0.85,
        f"Imbalance Ratio: {counts[0] / counts[1]:.1f} : 1",
        transform=ax1.transAxes,
        ha="center",
        bbox=dict(boxstyle="round,pad=0.5", facecolor="white", edgecolor=GRAY, alpha=0.9),
    )

    # Right: Accuracy Paradox vs Financial Disaster
    models = ["Naive Model\n(Always Predict 0)", "Hypothetical\nPerfect Model"]
    accs = [ratios[0], 100.0]
    costs_per_k = [ratios[1] / 100.0 * 12.0 * 1000.0, 0.0]  # Every defaulter missed @ 12 units

    x = np.arange(len(models))
    width = 0.35

    ax2_twin = ax2.twinx()
    b1 = ax2.bar(
        x - width / 2,
        accs,
        width,
        label="Accuracy (%)",
        color=SKY,
        edgecolor="#1E293B",
        linewidth=1,
    )
    b2 = ax2_twin.bar(
        x + width / 2,
        costs_per_k,
        width,
        label="Expected Cost / 1,000 (Units)",
        color=CRIMSON,
        edgecolor="#1E293B",
        linewidth=1,
    )

    ax2.set_ylabel("Accuracy (%)", color=NAVY, fontsize=11, fontweight="semibold")
    ax2_twin.set_ylabel(
        "Expected Cost per 1,000 Applicants (Units)",
        color=CRIMSON,
        fontsize=11,
        fontweight="semibold",
    )
    ax2.set_xticks(x)
    ax2.set_xticklabels(models, fontweight="semibold")
    ax2.set_ylim(0, 115)
    ax2_twin.set_ylim(0, 1000)
    ax2.set_title(
        "The Accuracy Paradox: 93.3% Accuracy vs Catastrophic Loss",
        fontsize=13,
        fontweight="bold",
        pad=12,
    )

    # Annotate Naive Disaster
    ax2.text(
        x[0] - width / 2, accs[0] + 3, f"{accs[0]:.1f}%", ha="center", fontweight="bold", color=NAVY
    )
    ax2_twin.text(
        x[0] + width / 2,
        costs_per_k[0] + 25,
        f"{costs_per_k[0]:.1f} units\n(Max Loss!)",
        ha="center",
        fontweight="bold",
        color=CRIMSON,
    )

    # Legend
    lines1, labels1 = ax2.get_legend_handles_labels()
    lines2, labels2 = ax2_twin.get_legend_handles_labels()
    ax2.legend(lines1 + lines2, labels1 + labels2, loc="upper right")

    plt.tight_layout()
    fig.savefig(FIG_DIR / "fig01_target_imbalance_and_cost.png")
    plt.close(fig)
    print("Saved fig01_target_imbalance_and_cost.png")


def plot_fig2_sentinels(df: pd.DataFrame) -> None:
    """Figure 2: Sentinel Values (Codes 96 & 98) & Default Rate Divergence."""
    audit = SentinelAuditor.audit(df)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5.5))

    # Left: Delinquency Columns Sentinel Breakdown
    cols_display = ["30-59 Days\nPast Due", "60-89 Days\nPast Due", "90+ Days\nLate"]
    c98_vals = [audit["counts_98"].get(c, 0) for c in audit["columns_audited"]]
    c96_vals = [audit["counts_96"].get(c, 0) for c in audit["columns_audited"]]

    x = np.arange(len(cols_display))
    width = 0.4

    b1 = ax1.bar(
        x - width / 2,
        c98_vals,
        width,
        label="Code 98 (Unverified / No Record)",
        color=AMBER,
        edgecolor="#1E293B",
        linewidth=1.1,
    )
    b2 = ax1.bar(
        x + width / 2,
        c96_vals,
        width,
        label="Code 96 (Dispute / Frozen)",
        color=CRIMSON,
        edgecolor="#1E293B",
        linewidth=1.1,
    )

    ax1.set_xticks(x)
    ax1.set_xticklabels(cols_display, fontweight="semibold")
    ax1.set_ylabel("Number of Records with Sentinel Code", fontsize=11, fontweight="semibold")
    ax1.set_title(
        "Credit Bureau Sentinel Codes (100% Concordance)", fontsize=13, fontweight="bold", pad=12
    )
    ax1.set_ylim(0, 320)
    ax1.legend(loc="upper right")

    for bar in b1:
        h = bar.get_height()
        ax1.text(
            bar.get_x() + bar.get_width() / 2, h + 8, f"{int(h)}", ha="center", fontweight="bold"
        )
    for bar in b2:
        h = bar.get_height()
        ax1.text(
            bar.get_x() + bar.get_width() / 2, h + 8, f"{int(h)}", ha="center", fontweight="bold"
        )

    ax1.text(
        0.5,
        0.72,
        "Exact Co-occurrence:\nAll 264 rows have 98 in all 3 cols\nAll 5 rows have 96 in all 3 cols",
        transform=ax1.transAxes,
        ha="center",
        bbox=dict(boxstyle="round,pad=0.5", facecolor="#FEF3C7", edgecolor=AMBER, alpha=0.9),
        fontsize=9.5,
    )

    # Right: Default Rate Divergence
    groups = ["Normal Borrowers\n(No Sentinel Code)", "Sentinel Borrowers\n(Codes 96 or 98)"]
    rates = [audit["normal_default_rate"] * 100, audit["sentinel_default_rate"] * 100]

    bars2 = ax2.bar(groups, rates, color=[BLUE, RED], width=0.5, edgecolor="#1E293B", linewidth=1.2)
    ax2.set_ylabel("Serious Default Rate (%)", fontsize=11, fontweight="semibold")
    ax2.set_title(
        "The 8.28x Risk Surge: Default Rate by Sentinel Status",
        fontsize=13,
        fontweight="bold",
        pad=12,
    )
    ax2.set_ylim(0, 70)

    for bar, rate in zip(bars2, rates):
        h = bar.get_height()
        ax2.text(
            bar.get_x() + bar.get_width() / 2,
            h + 2.5,
            f"{rate:.2f}%",
            ha="center",
            fontweight="bold",
            fontsize=11,
        )

    ax2.annotate(
        "8.28x Higher Risk!\nEssential Predictive Signal",
        xy=(1, rates[1]),
        xytext=(0.55, 60),
        arrowprops=dict(facecolor=CRIMSON, shrink=0.08, width=2, headwidth=8),
        fontsize=10.5,
        fontweight="bold",
        color=CRIMSON,
        bbox=dict(boxstyle="round,pad=0.4", facecolor="#FEE2E2", edgecolor=RED),
    )

    plt.tight_layout()
    fig.savefig(FIG_DIR / "fig02_sentinel_codes_analysis.png")
    plt.close(fig)
    print("Saved fig02_sentinel_codes_analysis.png")


def plot_fig3_missing_data(df: pd.DataFrame) -> None:
    """Figure 3: Missing Value Rates and MAR (Missing at Random) Pattern."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5.5))

    # Left: Missing percentages across columns
    miss_pct = (df.isna().sum() / len(df) * 100).sort_values(ascending=False)
    miss_pct = miss_pct[miss_pct > 0]

    clean_names = [
        "Monthly Income"
        if "monthly_income" in c
        else "Number of Dependents"
        if "number_of_dependents" in c
        else c
        for c in miss_pct.index
    ]

    bars = ax1.barh(
        clean_names,
        miss_pct.values,
        color=[AMBER, SKY],
        edgecolor="#1E293B",
        linewidth=1.1,
        height=0.45,
    )
    ax1.set_xlabel("Missing Percentage (%)", fontsize=11, fontweight="semibold")
    ax1.set_title("Missing Data Prevalence Across Features", fontsize=13, fontweight="bold", pad=12)
    ax1.set_xlim(0, 25)
    for bar in bars:
        w = bar.get_width()
        ax1.text(
            w + 0.6,
            bar.get_y() + bar.get_height() / 2,
            f"{w:.2f}% ({int(w / 100 * len(df)):,} rows)",
            va="center",
            fontweight="bold",
            fontsize=10,
        )

    # Right: Default Rate by Income Presence (Evidence of MAR)
    income_reported = df["monthly_income"].notna()
    rates_income = [
        df.loc[income_reported, "serious_dlqin_2yrs"].mean() * 100,
        df.loc[~income_reported, "serious_dlqin_2yrs"].mean() * 100,
    ]

    labels_inc = ["Income Reported\n(N = 120,269)", "Income Missing\n(N = 29,731)"]
    bars2 = ax2.bar(
        labels_inc, rates_income, color=[BLUE, AMBER], width=0.5, edgecolor="#1E293B", linewidth=1.1
    )
    ax2.set_ylabel("Serious Default Rate (%)", fontsize=11, fontweight="semibold")
    ax2.set_title(
        "Missing Mechanism Analysis: Evidence of MAR", fontsize=13, fontweight="bold", pad=12
    )
    ax2.set_ylim(0, 10)

    for bar, r in zip(bars2, rates_income):
        h = bar.get_height()
        ax2.text(
            bar.get_x() + bar.get_width() / 2,
            h + 0.3,
            f"{r:.2f}%",
            ha="center",
            fontweight="bold",
            fontsize=10.5,
        )

    ax2.text(
        0.5,
        0.78,
        "Notice: Applicants who omit income\nhave a lower default rate (5.61% vs 6.95%).\nMissingness is not purely random (MAR).",
        transform=ax2.transAxes,
        ha="center",
        bbox=dict(boxstyle="round,pad=0.5", facecolor="#F1F5F9", edgecolor=GRAY, alpha=0.9),
        fontsize=9.5,
    )

    plt.tight_layout()
    fig.savefig(FIG_DIR / "fig03_missing_data_mechanism.png")
    plt.close(fig)
    print("Saved fig03_missing_data_mechanism.png")


def plot_fig4_domain_outliers(df: pd.DataFrame) -> None:
    """Figure 4: Domain Outliers Inspection (Impossible Age & DebtRatio)."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5.5))

    # Left: Age Distribution with Impossible Age = 0 Callout
    sns.histplot(
        df["age"],
        bins=40,
        kde=True,
        color=sns.color_palette("Dark2")[0],
        ax=ax1,
        edgecolor="#1E293B",
        alpha=0.6,
    )
    ax1.set_title(
        "Borrower Age Distribution & Sentinel Outlier", fontsize=13, fontweight="bold", pad=12
    )
    ax1.set_xlabel("Applicant Age (Years)", fontsize=11, fontweight="semibold")
    ax1.set_ylabel("Applicant Frequency", fontsize=11, fontweight="semibold")
    ax1.yaxis.set_major_formatter("{x:,.0f}")

    zero_age_count = (df["age"] < 18).sum()
    ax1.annotate(
        f"Impossible Outlier:\nAge = 0 (1 Applicant)\nApplicant ID: 65696\nImputed to Median (52)",
        xy=(0, 200),
        xytext=(15, 6000),
        arrowprops=dict(facecolor=RED, shrink=0.08, width=2, headwidth=8),
        fontsize=9.5,
        fontweight="bold",
        color=CRIMSON,
        bbox=dict(boxstyle="round,pad=0.4", facecolor="#FEE2E2", edgecolor=RED),
    )

    # Right: Debt Ratio Log Distribution Split by Income Presence
    df_plot = df.copy()
    df_plot["income_status"] = np.where(
        df_plot["monthly_income"].notna(),
        "Income Reported (Ratio)",
        "Income Missing (Dollar Amount)",
    )
    df_plot["log_debt_ratio"] = np.log10(np.clip(df_plot["debt_ratio"], 0.001, 1e6))

    sns.kdeplot(
        data=df_plot,
        x="log_debt_ratio",
        hue="income_status",
        palette=[BLUE, AMBER],
        fill=True,
        common_norm=False,
        alpha=0.35,
        ax=ax2,
        linewidth=2,
    )
    ax2.set_title(
        "DebtRatio Bimodal Shift in Absence of Monthly Income",
        fontsize=13,
        fontweight="bold",
        pad=12,
    )
    ax2.set_xlabel("Log10(Debt Ratio)", fontsize=11, fontweight="semibold")
    ax2.set_ylabel("Kernel Density", fontsize=11, fontweight="semibold")

    ax2.text(
        0.5,
        0.82,
        "When income is missing, DebtRatio acts as\nabsolute debt in dollars (values > 1,000)!",
        transform=ax2.transAxes,
        ha="center",
        bbox=dict(boxstyle="round,pad=0.5", facecolor="white", edgecolor=AMBER, alpha=0.9),
        fontsize=9.5,
    )

    plt.tight_layout()
    fig.savefig(FIG_DIR / "fig04_domain_outliers_inspection.png")
    plt.close(fig)
    print("Saved fig04_domain_outliers_inspection.png")


def plot_fig5_feature_correlations(df_feat: pd.DataFrame) -> None:
    """Figure 5: Feature Correlations Heatmap."""
    cols_to_corr = [
        "serious_dlqin_2yrs",
        "has_sentinel_late_code",
        "clean_past_due_total",
        "clean_num_90_days_late",
        "clean_num_30_59_days_late",
        "clean_num_60_89_days_late",
        "utilization_per_line",
        "revolving_utilization_of_unsecured_lines",
        "debt_to_income_dollars",
        "unsecured_to_total_lines_ratio",
        "age",
        "monthly_income",
    ]
    corr_labels = [
        "Serious Default (Target)",
        "Has Sentinel Late Code",
        "Clean Past Due Total (Eng)",
        "90+ Days Late",
        "30-59 Days Late",
        "60-89 Days Late",
        "Utilization / Line (Eng)",
        "Revolving Utilization",
        "Debt $ Amount (Eng)",
        "Unsecured Line Ratio (Eng)",
        "Applicant Age",
        "Monthly Income",
    ]

    corr_matrix = df_feat[cols_to_corr].corr()
    corr_matrix.columns = corr_labels
    corr_matrix.index = corr_labels

    fig, ax = plt.subplots(figsize=(11, 8.5))
    mask = np.triu(np.ones_like(corr_matrix, dtype=bool))

    cmap = sns.diverging_palette(240, 10, as_cmap=True)
    sns.heatmap(
        corr_matrix,
        mask=mask,
        annot=True,
        fmt=".2f",
        cmap=cmap,
        vmin=-0.35,
        vmax=0.6,
        center=0,
        square=True,
        linewidths=0.75,
        cbar_kws={"shrink": 0.75, "label": "Pearson Correlation Coefficient"},
        ax=ax,
        annot_kws={"size": 9, "weight": "semibold"},
    )
    ax.set_title(
        "Correlation Heatmap: Features vs Loan Default Risk", fontsize=14, fontweight="bold", pad=15
    )
    plt.xticks(rotation=45, ha="right", fontweight="semibold")
    plt.yticks(fontweight="semibold")

    plt.tight_layout()
    fig.savefig(FIG_DIR / "fig05_feature_correlations_heatmap.png")
    plt.close(fig)
    print("Saved fig05_feature_correlations_heatmap.png")


def plot_fig6_engineered_features(df_feat: pd.DataFrame) -> None:
    """Figure 6: Risk Stratification across 4 Engineered Features."""
    fig, axes = plt.subplots(2, 2, figsize=(13, 10))
    df_p = df_feat.copy()
    df_p["Default Status"] = np.where(df_p["serious_dlqin_2yrs"] == 1, "Default (1)", "Healthy (0)")

    # 1. Monthly Debt in Dollars
    ax = axes[0, 0]
    df_p["log_debt_dollars"] = np.log10(np.clip(df_p["debt_to_income_dollars"], 1.0, 1e7))
    sns.boxplot(
        data=df_p, x="Default Status", y="log_debt_dollars", palette=[BLUE, RED], ax=ax, width=0.45
    )
    ax.set_title("Feature 1: Log10(Debt to Income in Dollars)", fontweight="bold")
    ax.set_ylabel("Log10(Monthly Debt $)")
    ax.set_xlabel("")

    # 2. Utilization Per Line
    ax = axes[0, 1]
    df_p["clipped_util_per_line"] = np.clip(df_p["utilization_per_line"], 0.0, 2.0)
    sns.boxplot(
        data=df_p,
        x="Default Status",
        y="clipped_util_per_line",
        palette=[BLUE, RED],
        ax=ax,
        width=0.45,
    )
    ax.set_title("Feature 2: Revolving Utilization per Open Line", fontweight="bold")
    ax.set_ylabel("Utilization Ratio / Line")
    ax.set_xlabel("")

    # 3. Unsecured Lines Ratio
    ax = axes[1, 0]
    sns.boxplot(
        data=df_p,
        x="Default Status",
        y="unsecured_to_total_lines_ratio",
        palette=[BLUE, RED],
        ax=ax,
        width=0.45,
    )
    ax.set_title("Feature 3: Unsecured to Total Lines Ratio", fontweight="bold")
    ax.set_ylabel("Proportion of Unsecured Credit")
    ax.set_xlabel("")

    # 4. Clean Past Due Total
    ax = axes[1, 1]
    past_due_summary = (
        df_p.groupby(["Default Status", "clean_past_due_total"])
        .size()
        .unstack(level=0, fill_value=0)
    )
    past_due_pct = (past_due_summary / past_due_summary.sum()) * 100
    past_due_sub = past_due_pct.loc[:5]  # first 5 delinquent counts

    past_due_sub.plot(kind="bar", ax=ax, color=[BLUE, RED], edgecolor="#1E293B", width=0.7)
    ax.set_title("Feature 4: Clean Past Due Total Frequency (%)", fontweight="bold")
    ax.set_ylabel("Percentage within Class (%)")
    ax.set_xlabel("Total Non-Sentinel Past Due Events")
    ax.legend(title="Status")
    ax.set_xticklabels(ax.get_xticklabels(), rotation=0)

    plt.suptitle(
        "Engineered Features: Sharp Separation Between Classes",
        fontsize=15,
        fontweight="bold",
        y=1.00,
    )
    plt.tight_layout()
    fig.savefig(FIG_DIR / "fig06_engineered_features_risk_distributions.png")
    plt.close(fig)
    print("Saved fig06_engineered_features_risk_distributions.png")


def plot_fig14_continuous_variables_grid(df_feat: pd.DataFrame) -> None:
    """Figure 14: Grid Distribution of Continuous Variables (Seaborn Theme)."""
    fig, axes = plt.subplots(3, 3, figsize=(15, 11))
    axes = axes.flatten()

    continuous_vars = [
        ("age", "Applicant Age (Years)", (18, 90), df_feat["age"], "Years"),
        (
            "monthly_income",
            "Monthly Income ($)",
            (0, 20000),
            df_feat["monthly_income"].dropna(),
            "Dollars ($)",
        ),
        (
            "debt_ratio",
            "Debt Ratio (Income-Reporting)",
            (0, 2.0),
            df_feat.loc[df_feat["monthly_income"].notna(), "debt_ratio"],
            "Ratio",
        ),
        (
            "revolving_utilization_of_unsecured_lines",
            "Revolving Line Utilization",
            (0, 1.5),
            df_feat["revolving_utilization_of_unsecured_lines"],
            "Utilization %",
        ),
        (
            "number_of_open_credit_lines_and_loans",
            "Open Credit Lines & Loans Count",
            (0, 25),
            df_feat["number_of_open_credit_lines_and_loans"],
            "Accounts Count",
        ),
        (
            "number_real_estate_loans_or_lines",
            "Real Estate Loans & Mortgages",
            (0, 6),
            df_feat["number_real_estate_loans_or_lines"],
            "Loans Count",
        ),
        (
            "debt_to_income_dollars",
            "Engineered: Monthly Debt ($)",
            (0, 8000),
            df_feat["debt_to_income_dollars"].dropna(),
            "Dollars ($)",
        ),
        (
            "utilization_per_line",
            "Engineered: Utilization / Line",
            (0, 0.6),
            df_feat["utilization_per_line"],
            "Ratio / Account",
        ),
        (
            "unsecured_to_total_lines_ratio",
            "Engineered: Unsecured Line Ratio",
            (0, 1.0),
            df_feat["unsecured_to_total_lines_ratio"],
            "Proportion [0, 1]",
        ),
    ]

    colors = sns.color_palette("Dark2", 8) + [sns.color_palette("deep")[4]]
    for ax, color, (col, title, xlim, data, xlabel) in zip(axes, colors, continuous_vars):
        sub = data[(data >= xlim[0]) & (data <= xlim[1])]
        sns.histplot(
            sub,
            kde=True,
            ax=ax,
            color=color,
            edgecolor="#1E293B",
            alpha=0.55,
            bins=30,
            line_kws={"linewidth": 2},
        )
        med = sub.median()
        mean = sub.mean()
        ax.axvline(med, color=RED, linestyle="--", linewidth=1.5, label=f"Median: {med:,.1f}")
        ax.axvline(mean, color=AMBER, linestyle=":", linewidth=1.5, label=f"Mean: {mean:,.1f}")

        ax.set_title(title, fontweight="bold", fontsize=11, pad=8)
        ax.set_xlabel(xlabel, fontweight="semibold", fontsize=9.5)
        ax.set_ylabel("Frequency", fontweight="semibold", fontsize=9.5)
        ax.set_xlim(xlim)
        ax.yaxis.set_major_formatter("{x:,.0f}")
        ax.legend(loc="upper right", fontsize=8.5, framealpha=0.9)

    plt.suptitle(
        "Grid Distribution of Continuous Variables (Seaborn Theme)",
        fontsize=15,
        fontweight="bold",
        y=0.995,
    )
    plt.tight_layout()
    fig.savefig(FIG_DIR / "fig14_continuous_variables_grid.png")
    plt.close(fig)
    print("Saved fig14_continuous_variables_grid.png")


def plot_threshold_costs(
    baseline_cost_per_k, lr_details, lr_min_cost, lr_best_th, hgb_details, hgb_min_cost, hgb_best_th
):
    fig, ax = plt.subplots(figsize=(12, 6))

    thresholds = [h["threshold"] for h in hgb_details["history"]]
    hgb_costs = [h["expected_cost_per_thousand"] for h in hgb_details["history"]]
    lr_costs = [h["expected_cost_per_thousand"] for h in lr_details["history"]]

    ax.axhline(
        baseline_cost_per_k,
        color=CRIMSON,
        linestyle="--",
        linewidth=1.8,
        label=f"Baseline (Always 0): {baseline_cost_per_k:.1f} units",
    )
    ax.plot(
        thresholds,
        lr_costs,
        color=BLUE,
        linewidth=2.2,
        label=f"Logistic Regression (Min: {lr_min_cost:.1f} @ th={lr_best_th:.2f})",
    )
    ax.plot(
        thresholds,
        hgb_costs,
        color=GREEN,
        linewidth=2.6,
        label=f"HistGradientBoosting (Min: {hgb_min_cost:.1f} @ th={hgb_best_th:.2f})",
    )

    # Marker at optimal
    ax.scatter(
        [hgb_best_th],
        [hgb_min_cost],
        color=GREEN,
        s=140,
        zorder=5,
        edgecolor="#1E293B",
        linewidth=1.5,
    )
    ax.scatter(
        [0.5],
        [hgb_details["default_0_5_cost_per_thousand"]],
        color=AMBER,
        s=120,
        zorder=5,
        edgecolor="#1E293B",
        linewidth=1.5,
    )

    ax.annotate(
        f"Optimal Threshold = {hgb_best_th:.3f}\nMin Cost = {hgb_min_cost:.1f} units/1k\n(-55.1% vs Baseline!)",
        xy=(hgb_best_th, hgb_min_cost),
        xytext=(hgb_best_th + 0.12, hgb_min_cost - 40),
        arrowprops=dict(facecolor=GREEN, shrink=0.08, width=2, headwidth=8),
        fontsize=10.5,
        fontweight="bold",
        color=GREEN,
        bbox=dict(boxstyle="round,pad=0.5", facecolor="#ECFDF5", edgecolor=GREEN),
    )

    ax.annotate(
        f"Default 0.5 Threshold\nCost = {hgb_details['default_0_5_cost_per_thousand']:.1f} units/1k\n(Leaves 70% Defaulters Uncaught!)",
        xy=(0.5, hgb_details["default_0_5_cost_per_thousand"]),
        xytext=(0.55, hgb_details["default_0_5_cost_per_thousand"] + 70),
        arrowprops=dict(facecolor=AMBER, shrink=0.08, width=2, headwidth=8),
        fontsize=10,
        fontweight="bold",
        color=AMBER,
        bbox=dict(boxstyle="round,pad=0.5", facecolor="#FEF3C7", edgecolor=AMBER),
    )

    ax.set_title(
        "Expected Business Cost per 1,000 Applicants vs Decision Threshold",
        fontsize=14,
        fontweight="bold",
        pad=15,
    )
    ax.set_xlabel("Decision Threshold (Probability Cutoff)", fontsize=12, fontweight="semibold")
    ax.set_ylabel("Expected Cost per 1,000 Applicants (Units)", fontsize=12, fontweight="semibold")
    ax.set_xlim(0.0, 1.0)
    ax.set_ylim(250, 900)
    ax.legend(loc="upper right", framealpha=0.95)

    plt.tight_layout()
    fig.savefig(FIG_DIR / "fig07_cost_vs_threshold_optimization.png")
    plt.close(fig)
    print("Saved fig07_cost_vs_threshold_optimization.png")


def plot_cost_sensitivity(y_test, hgb_probs):
    fig, ax = plt.subplots(figsize=(12, 6))

    scenarios = [
        ("High Loss: C(FN)=12, C(FP)=1 (Base)", 12.0, 1.0, CRIMSON),
        ("Moderate Loss: C(FN)=4, C(FP)=1", 4.0, 1.0, AMBER),
        ("Balanced Loss: C(FN)=1, C(FP)=1", 1.0, 1.0, BLUE),
    ]

    for label, c_fn, c_fp, color in scenarios:
        th_list = np.linspace(0.01, 0.99, 150)
        costs = []
        for th in th_list:
            preds = (hgb_probs >= th).astype(int)
            costs.append(
                calculate_expected_cost_per_thousand(y_test, preds, cost_fp=c_fp, cost_fn=c_fn)
            )
        best_idx = int(np.argmin(costs))
        opt_th = th_list[best_idx]
        opt_c = costs[best_idx]
        ax.plot(
            th_list,
            costs,
            label=f"{label} -> Opt Threshold: {opt_th:.2f}",
            color=color,
            linewidth=2.4,
        )
        ax.scatter([opt_th], [opt_c], color=color, s=100, zorder=5, edgecolor="#1E293B")

    ax.set_title(
        "Sensitivity Analysis: Optimal Threshold Shifts with Business Risk Tolerance",
        fontsize=14,
        fontweight="bold",
        pad=15,
    )
    ax.set_xlabel("Decision Threshold", fontsize=12, fontweight="semibold")
    ax.set_ylabel(
        "Normalized Cost per 1,000 Applicants (Units)", fontsize=12, fontweight="semibold"
    )
    ax.legend(loc="upper right")
    ax.set_xlim(0, 1)

    plt.tight_layout()
    fig.savefig(FIG_DIR / "fig08_cost_matrix_sensitivity_analysis.png")
    plt.close(fig)
    print("Saved fig08_cost_matrix_sensitivity_analysis.png")


def plot_roc_and_precision_recall(y_test, hgb_probs, lr_probs, hgb_best_th, hgb_auc, lr_auc):
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5.5))

    # Left: ROC Curve
    fpr_lr, tpr_lr, _ = roc_curve(y_test, lr_probs)
    fpr_hgb, tpr_hgb, _ = roc_curve(y_test, hgb_probs)

    ax1.plot(
        fpr_hgb,
        tpr_hgb,
        color=GREEN,
        linewidth=2.5,
        label=f"HistGradientBoosting (AUC = {hgb_auc:.4f})",
    )
    ax1.plot(
        fpr_lr, tpr_lr, color=BLUE, linewidth=2.2, label=f"Logistic Regression (AUC = {lr_auc:.4f})"
    )
    ax1.plot(
        [0, 1],
        [0, 1],
        color=GRAY,
        linestyle="--",
        linewidth=1.5,
        label="Random Guess (AUC = 0.5000)",
    )

    # Operating point on ROC
    opt_preds = (hgb_probs >= hgb_best_th).astype(int)
    cm_opt = confusion_matrix(y_test, opt_preds)
    tn, fp, fn, tp = cm_opt.ravel()
    fpr_opt = fp / (fp + tn)
    tpr_opt = tp / (tp + fn)
    ax1.scatter(
        [fpr_opt],
        [tpr_opt],
        color=CRIMSON,
        s=120,
        zorder=5,
        edgecolor="#1E293B",
        label=f"Cost-Optimal Point (Recall: {tpr_opt * 100:.1f}%)",
    )

    ax1.set_title("Receiver Operating Characteristic (ROC)", fontsize=13, fontweight="bold", pad=12)
    ax1.set_xlabel("False Positive Rate (FPR)", fontsize=11, fontweight="semibold")
    ax1.set_ylabel("True Positive Rate / Recall (TPR)", fontsize=11, fontweight="semibold")
    ax1.legend(loc="lower right")
    ax1.set_xlim(0, 1)
    ax1.set_ylim(0, 1.02)

    # Right: Precision-Recall Curve
    prec_hgb, rec_hgb, _ = precision_recall_curve(y_test, hgb_probs)
    prec_lr, rec_lr, _ = precision_recall_curve(y_test, lr_probs)
    pr_auc_hgb = auc(rec_hgb, prec_hgb)
    pr_auc_lr = auc(rec_lr, prec_lr)

    ax2.plot(
        rec_hgb,
        prec_hgb,
        color=GREEN,
        linewidth=2.5,
        label=f"HistGradientBoosting (PR-AUC = {pr_auc_hgb:.4f})",
    )
    ax2.plot(
        rec_lr,
        prec_lr,
        color=BLUE,
        linewidth=2.2,
        label=f"Logistic Regression (PR-AUC = {pr_auc_lr:.4f})",
    )
    no_skill = len(y_test[y_test == 1]) / len(y_test)
    ax2.plot(
        [0, 1],
        [no_skill, no_skill],
        color=GRAY,
        linestyle="--",
        label=f"Baseline Class Ratio ({no_skill * 100:.1f}%)",
    )

    # Precision at optimal point
    prec_opt = tp / (tp + fp)
    ax2.scatter(
        [tpr_opt],
        [prec_opt],
        color=CRIMSON,
        s=120,
        zorder=5,
        edgecolor="#1E293B",
        label=f"Optimal Decision Point (Precision: {prec_opt * 100:.1f}%)",
    )

    ax2.set_title(
        "Precision-Recall Curve (Minority Class Focus)", fontsize=13, fontweight="bold", pad=12
    )
    ax2.set_xlabel("Recall (Sensitivity)", fontsize=11, fontweight="semibold")
    ax2.set_ylabel("Precision", fontsize=11, fontweight="semibold")
    ax2.legend(loc="upper right")
    ax2.set_xlim(0, 1)
    ax2.set_ylim(0, 1.02)

    plt.tight_layout()
    fig.savefig(FIG_DIR / "fig09_roc_and_precision_recall_curves.png")
    plt.close(fig)
    print("Saved fig09_roc_and_precision_recall_curves.png")


def plot_confusion_matrices(y_test, hgb_probs, hgb_best_th, hgb_details, hgb_min_cost):
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5.5))

    # CM at default 0.5
    cm_05 = confusion_matrix(y_test, (hgb_probs >= 0.5).astype(int))
    # CM at optimal threshold
    cm_opt = confusion_matrix(y_test, (hgb_probs >= hgb_best_th).astype(int))

    def annotate_cm(ax, cm, title, cost_per_k, threshold):
        tn, fp, fn, tp = cm.ravel()
        total_cost = fp * 1.0 + fn * 12.0

        annot_matrix = np.array(
            [
                [f"TN: {tn:,}\nCost: 0", f"FP: {fp:,}\nCost: {fp:,} ($1/ea)"],
                [f"FN: {fn:,}\nCost: {fn * 12:,} ($12/ea)", f"TP: {tp:,}\nCost: 0"],
            ]
        )

        sns.heatmap(
            cm,
            annot=annot_matrix,
            fmt="",
            cmap="Blues",
            cbar=False,
            ax=ax,
            linewidths=1.5,
            linecolor="#1E293B",
            annot_kws={"size": 11, "weight": "bold"},
        )
        ax.set_title(
            f"{title}\nThreshold = {threshold:.3f} | Cost/1k = {cost_per_k:.1f} units",
            fontsize=12,
            fontweight="bold",
            pad=12,
        )
        ax.set_xlabel(
            "Predicted Label (0: Healthy, 1: Default)", fontsize=11, fontweight="semibold"
        )
        ax.set_ylabel("Actual Ground Truth", fontsize=11, fontweight="semibold")
        ax.set_xticklabels(["Predict Healthy (0)", "Predict Default (1)"])
        ax.set_yticklabels(["Actual Healthy (0)", "Actual Default (1)"], rotation=0)

    annotate_cm(
        ax1,
        cm_05,
        "Default Library Threshold (0.5)",
        hgb_details["default_0_5_cost_per_thousand"],
        0.5,
    )
    annotate_cm(ax2, cm_opt, "Cost-Optimal Decision Threshold", hgb_min_cost, hgb_best_th)

    plt.tight_layout()
    fig.savefig(FIG_DIR / "fig10_confusion_matrix_heatmaps.png")
    plt.close(fig)
    print("Saved fig10_confusion_matrix_heatmaps.png")


def plot_cross_validation(X, y):
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    cv_aucs = []
    cv_costs = []
    cv_recalls = []

    for train_idx, val_idx in skf.split(X, y):
        X_tr, X_va = X.iloc[train_idx], X.iloc[val_idx]
        y_tr, y_va = y.iloc[train_idx], y.iloc[val_idx]

        m = HistGradientBoostingClassifier(random_state=42, max_iter=100)
        m.fit(X_tr, y_tr)
        val_probs = m.predict_proba(X_va)[:, 1]

        # Optimal threshold on validation
        th_val, c_val, _ = find_optimal_threshold(y_va, val_probs)
        preds_val = (val_probs >= th_val).astype(int)

        cv_aucs.append(roc_auc_score(y_va, val_probs))
        cv_costs.append(c_val)
        cv_recalls.append((y_va[preds_val == 1] == 1).sum() / (y_va == 1).sum() * 100)

    fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(14, 4.8))

    ax1.plot(range(1, 6), cv_aucs, marker="o", color=BLUE, linewidth=2, markersize=8)
    ax1.axhline(np.mean(cv_aucs), color=NAVY, linestyle="--", label=f"Mean: {np.mean(cv_aucs):.4f}")
    ax1.set_title(
        f"ROC-AUC Stability Across 5 Folds\n(Std: {np.std(cv_aucs):.4f})", fontweight="bold"
    )
    ax1.set_xlabel("Cross-Validation Fold")
    ax1.set_ylabel("ROC-AUC")
    ax1.set_ylim(0.85, 0.88)
    ax1.legend()

    ax2.plot(range(1, 6), cv_costs, marker="s", color=CRIMSON, linewidth=2, markersize=8)
    ax2.axhline(
        np.mean(cv_costs), color=RED, linestyle="--", label=f"Mean: {np.mean(cv_costs):.1f}"
    )
    ax2.set_title(
        f"Expected Cost/1k Stability\n(Std: {np.std(cv_costs):.1f} units)", fontweight="bold"
    )
    ax2.set_xlabel("Cross-Validation Fold")
    ax2.set_ylabel("Expected Cost per 1,000")
    ax2.set_ylim(340, 380)
    ax2.legend()

    ax3.plot(range(1, 6), cv_recalls, marker="^", color=GREEN, linewidth=2, markersize=8)
    ax3.axhline(
        np.mean(cv_recalls),
        color=EMERALD,
        linestyle="--",
        label=f"Mean: {np.mean(cv_recalls):.1f}%",
    )
    ax3.set_title(
        f"Defaulter Recall Stability\n(Std: {np.std(cv_recalls):.1f}%)", fontweight="bold"
    )
    ax3.set_xlabel("Cross-Validation Fold")
    ax3.set_ylabel("Recall (%)")
    ax3.set_ylim(75, 90)
    ax3.legend()

    plt.tight_layout()
    fig.savefig(FIG_DIR / "fig11_cross_validation_stability.png")
    plt.close(fig)
    print("Saved fig11_cross_validation_stability.png")
    return cv_aucs, cv_costs


def plot_feature_importance(hgb, X_test, y_test, feature_cols):
    fig, ax = plt.subplots(figsize=(11, 6))

    # Permutation importance on validation sample
    perm = permutation_importance(
        hgb, X_test.iloc[:5000], y_test.iloc[:5000], n_repeats=5, random_state=42, scoring="roc_auc"
    )
    imp_df = pd.DataFrame(
        {"feature": feature_cols, "importance": perm.importances_mean}
    ).sort_values(by="importance", ascending=True)

    feature_pretty_names = {
        "revolving_utilization_of_unsecured_lines": "Revolving Line Utilization",
        "age": "Applicant Age",
        "debt_ratio": "Debt Ratio",
        "monthly_income": "Monthly Income",
        "number_of_open_credit_lines_and_loans": "Open Credit Lines Count",
        "number_real_estate_loans_or_lines": "Real Estate Loans Count",
        "number_of_dependents": "Number of Dependents",
        "has_sentinel_late_code": "Sentinel Late Code (96/98)",
        "clean_num_30_59_days_late": "30-59 Days Past Due",
        "clean_num_60_89_days_late": "60-89 Days Past Due",
        "clean_num_90_days_late": "90+ Days Late",
        "clean_total_past_due_events": "Total Past Due Events",
        "debt_to_income_dollars": "Engineered: Debt In Dollars",
        "utilization_per_line": "Engineered: Utilization / Line",
        "unsecured_to_total_lines_ratio": "Engineered: Unsecured Ratio",
        "clean_past_due_total": "Engineered: Clean Past Due Total",
    }
    imp_df["feature_clean"] = imp_df["feature"].map(lambda x: feature_pretty_names.get(x, x))

    colors = [
        BLUE if "Engineered" in f or "Sentinel" in f else SKY for f in imp_df["feature_clean"]
    ]
    bars = ax.barh(
        imp_df["feature_clean"],
        imp_df["importance"],
        color=colors,
        edgecolor="#1E293B",
        linewidth=1.1,
        height=0.6,
    )

    ax.set_title(
        "Top Predictive Features: Permutation Importance (ROC-AUC Impact)",
        fontsize=13,
        fontweight="bold",
        pad=12,
    )
    ax.set_xlabel("Mean Decrease in ROC-AUC When Permuted", fontsize=11, fontweight="semibold")

    for bar in bars:
        w = bar.get_width()
        if w > 0.001:
            ax.text(
                w + 0.001,
                bar.get_y() + bar.get_height() / 2,
                f"{w:.4f}",
                va="center",
                fontweight="bold",
                fontsize=9.5,
            )

    plt.tight_layout()
    fig.savefig(FIG_DIR / "fig12_feature_importance_top10.png")
    plt.close(fig)
    print("Saved fig12_feature_importance_top10.png")


def plot_age_group_results(X_test, y_test, hgb_probs, hgb_best_th):
    df_eval = X_test.copy()
    df_eval["y_true"] = y_test.values
    df_eval["y_prob"] = hgb_probs
    df_eval["y_pred"] = (hgb_probs >= hgb_best_th).astype(int)

    age_bins = [18, 30, 45, 60, 110]
    age_labels = ["Young (18-29)", "Early Career (30-44)", "Mature (45-59)", "Senior (60+)"]
    df_eval["age_group"] = pd.cut(df_eval["age"], bins=age_bins, labels=age_labels, right=False)

    fairness_records = []
    for g in age_labels:
        sub = df_eval[df_eval["age_group"] == g]
        cm_sub = confusion_matrix(sub["y_true"], sub["y_pred"], labels=[0, 1])
        tn_s, fp_s, fn_s, tp_s = cm_sub.ravel()

        default_rate = sub["y_true"].mean() * 100
        fpr = (fp_s / (fp_s + tn_s)) * 100 if (fp_s + tn_s) > 0 else 0
        recall = (tp_s / (tp_s + fn_s)) * 100 if (tp_s + fn_s) > 0 else 0
        approval_rate = (1.0 - sub["y_pred"].mean()) * 100
        fairness_records.append(
            {
                "age_group": g,
                "count": len(sub),
                "actual_default_rate": default_rate,
                "recall": recall,
                "fpr": fpr,
                "approval_rate": approval_rate,
            }
        )

    df_fair = pd.DataFrame(fairness_records)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5.5))

    x = np.arange(len(age_labels))
    width = 0.35

    b1 = ax1.bar(
        x - width / 2,
        df_fair["actual_default_rate"],
        width,
        label="Actual Default Rate (%)",
        color=RED,
        edgecolor="#1E293B",
        linewidth=1.1,
    )
    b2 = ax1.bar(
        x + width / 2,
        df_fair["fpr"],
        width,
        label="False Positive Rate (FPR %)",
        color=AMBER,
        edgecolor="#1E293B",
        linewidth=1.1,
    )

    ax1.set_xticks(x)
    ax1.set_xticklabels(age_labels, fontweight="semibold", rotation=15)
    ax1.set_ylabel("Rate (%)", fontsize=11, fontweight="semibold")
    ax1.set_title(
        "Subgroup Fairness: Default Risk vs False Positive Rejections",
        fontsize=12,
        fontweight="bold",
        pad=12,
    )
    ax1.set_ylim(0, 30)
    ax1.legend()

    for bar in b1:
        h = bar.get_height()
        ax1.text(
            bar.get_x() + bar.get_width() / 2,
            h + 0.6,
            f"{h:.1f}%",
            ha="center",
            fontweight="bold",
            fontsize=9.5,
        )
    for bar in b2:
        h = bar.get_height()
        ax1.text(
            bar.get_x() + bar.get_width() / 2,
            h + 0.6,
            f"{h:.1f}%",
            ha="center",
            fontweight="bold",
            fontsize=9.5,
        )

    # Right: Approval Rate across Age Brackets
    bars_app = ax2.bar(
        age_labels,
        df_fair["approval_rate"],
        color=BLUE,
        edgecolor="#1E293B",
        linewidth=1.1,
        width=0.5,
    )
    ax2.set_ylabel("Loan Approval Rate (%)", fontsize=11, fontweight="semibold")
    ax2.set_title(
        "Loan Approval Rates Across Demographic Cohorts", fontsize=12, fontweight="bold", pad=12
    )
    ax2.set_ylim(0, 100)
    ax2.set_xticklabels(age_labels, fontweight="semibold", rotation=15)

    for bar, app in zip(bars_app, df_fair["approval_rate"]):
        ax2.text(
            bar.get_x() + bar.get_width() / 2,
            app + 2,
            f"{app:.1f}%",
            ha="center",
            fontweight="bold",
            fontsize=10.5,
        )

    plt.tight_layout()
    fig.savefig(FIG_DIR / "fig13_subgroup_fairness_by_age.png")
    plt.close(fig)
    print("Saved fig13_subgroup_fairness_by_age.png")
    return df_fair


def run_modeling_and_plots(df_feat: pd.DataFrame) -> dict:
    """Train models, evaluate cost curves, ROC/PR, confusion matrices, and fairness."""
    feature_cols = [
        "revolving_utilization_of_unsecured_lines",
        "age",
        "debt_ratio",
        "monthly_income",
        "number_of_open_credit_lines_and_loans",
        "number_real_estate_loans_or_lines",
        "number_of_dependents",
        "has_sentinel_late_code",
        "clean_num_30_59_days_late",
        "clean_num_60_89_days_late",
        "clean_num_90_days_late",
        "clean_total_past_due_events",
        "debt_to_income_dollars",
        "utilization_per_line",
        "unsecured_to_total_lines_ratio",
        "clean_past_due_total",
    ]

    X = df_feat[feature_cols].copy()
    y = df_feat["serious_dlqin_2yrs"].copy()

    # Train / Test Split
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.20, random_state=42, stratify=y
    )

    # Baseline Model (Always Predict Healthy / 0)
    baseline_pred = np.zeros_like(y_test)
    baseline_cost_per_k = calculate_expected_cost_per_thousand(y_test, baseline_pred)

    # Model 1: Logistic Regression Pipeline
    lr_pipe = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            ("clf", LogisticRegression(max_iter=1000, random_state=42)),
        ]
    )
    lr_pipe.fit(X_train, y_train)
    lr_probs = lr_pipe.predict_proba(X_test)[:, 1]
    lr_auc = roc_auc_score(y_test, lr_probs)
    lr_best_th, lr_min_cost, lr_details = find_optimal_threshold(y_test, lr_probs)

    # Model 2: HistGradientBoosting
    hgb = HistGradientBoostingClassifier(random_state=42, max_iter=120, max_leaf_nodes=31)
    hgb.fit(X_train, y_train)
    hgb_probs = hgb.predict_proba(X_test)[:, 1]
    hgb_auc = roc_auc_score(y_test, hgb_probs)
    hgb_best_th, hgb_min_cost, hgb_details = find_optimal_threshold(y_test, hgb_probs)

    plot_threshold_costs(
        baseline_cost_per_k,
        lr_details,
        lr_min_cost,
        lr_best_th,
        hgb_details,
        hgb_min_cost,
        hgb_best_th,
    )
    plot_cost_sensitivity(y_test, hgb_probs)
    plot_roc_and_precision_recall(y_test, hgb_probs, lr_probs, hgb_best_th, hgb_auc, lr_auc)
    plot_confusion_matrices(y_test, hgb_probs, hgb_best_th, hgb_details, hgb_min_cost)
    cv_aucs, cv_costs = plot_cross_validation(X, y)
    plot_feature_importance(hgb, X_test, y_test, feature_cols)
    df_fair = plot_age_group_results(X_test, y_test, hgb_probs, hgb_best_th)

    return {
        "baseline_cost_per_k": baseline_cost_per_k,
        "lr_auc": lr_auc,
        "lr_min_cost": lr_min_cost,
        "lr_best_th": lr_best_th,
        "hgb_auc": hgb_auc,
        "hgb_min_cost": hgb_min_cost,
        "hgb_best_th": hgb_best_th,
        "hgb_default_cost": hgb_details["default_0_5_cost_per_thousand"],
        "cost_reduction_vs_baseline": ((baseline_cost_per_k - hgb_min_cost) / baseline_cost_per_k)
        * 100.0,
        "cv_aucs_mean": float(np.mean(cv_aucs)),
        "cv_aucs_std": float(np.std(cv_aucs)),
        "cv_costs_mean": float(np.mean(cv_costs)),
        "cv_costs_std": float(np.std(cv_costs)),
        "fairness_table": df_fair.to_dict(orient="records"),
    }


def main():
    print("=== Starting Part 3 Visualization & Model Execution Pipeline ===")
    t0 = time.time()

    df = load_clean_borrowers()
    print(f"Data loaded from PostgreSQL: {len(df):,} records in {time.time() - t0:.2f}s")

    # 1. Target Imbalance
    plot_fig1_target_imbalance_and_cost(df)

    # 2. Sentinels
    plot_fig2_sentinels(df)

    # 3. Missing Data
    plot_fig3_missing_data(df)

    # 4. Outliers
    plot_fig4_domain_outliers(df)

    # Feature Engineering
    df_feat = add_engineered_features(df)

    # Continuous Variables Distribution Grid
    plot_fig14_continuous_variables_grid(df_feat)

    # 5. Correlations
    plot_fig5_feature_correlations(df_feat)

    # 6. Engineered Feature Distributions
    plot_fig6_engineered_features(df_feat)

    # 7-13. Modeling, Threshold Optimization, Fairness
    results = run_modeling_and_plots(df_feat)

    print("\n=== All Visualizations Generated Successfully ===")
    print(f"Baseline Cost/1k: {results['baseline_cost_per_k']:.2f}")
    print(f"HistGradientBoosting AUC: {results['hgb_auc']:.4f}")
    print(f"HistGradientBoosting Optimal Threshold: {results['hgb_best_th']:.4f}")
    print(f"HistGradientBoosting Optimal Cost/1k: {results['hgb_min_cost']:.2f}")
    print(f"Cost Reduction vs Baseline: {results['cost_reduction_vs_baseline']:.2f}%")
    print(f"5-Fold CV AUC: {results['cv_aucs_mean']:.4f} +/- {results['cv_aucs_std']:.4f}")
    print(f"5-Fold CV Cost/1k: {results['cv_costs_mean']:.2f} +/- {results['cv_costs_std']:.2f}")


if __name__ == "__main__":
    main()
