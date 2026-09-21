#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analysis.py — 亚马逊畅销榜选品分析（命令行版）

读清洗后的畅销榜数据，产出 outputs/<时间戳>/ 下的图表(PNG)和结果表(CSV)。

用法:
    python scripts/analysis.py                 # 自动挑 data/ 下最新的清洗 CSV，输出到同名 outputs/<时间戳>/
    python scripts/analysis.py 某文件.csv      # 指定清洗后 CSV
"""

import glob
import os
import re
import sys

import matplotlib
matplotlib.use("Agg")  # 无界面后端，命令行直接跑
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# 中文字体，避免图表里的中文变成方框
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

OUT_DIR = "./outputs"


def _default_best_path():
    """自动挑 data/ 下最新的清洗 CSV（优先带时间戳文件夹，兼容旧的平铺文件）。"""
    candidates = glob.glob("data/*/clean_best_sellers*.csv")
    if not candidates:
        candidates = glob.glob("data/clean_best_sellers_all_category_*.csv")
    if candidates:
        return max(candidates, key=os.path.getmtime)
    return "data/clean_best_sellers_all_category_20251025.csv"  # 兜底默认名


def _run_id_from_path(path):
    """从清洗文件路径反推本次运行的时间戳，用于给 outputs/ 建同名文件夹。

    data/20260125_030500/clean_best_sellers.csv  -> 20260125_030500
    平铺旧文件则从文件名里的 8 位日期兜底。
    """
    p = os.path.normpath(path)
    parts = p.split(os.sep)
    if len(parts) >= 2 and parts[0] == "data":
        return parts[1]
    m = re.search(r"(\d{8})", os.path.basename(path))
    return m.group(1) if m else "run"


def save_fig(fig, name):
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, name)
    fig.savefig(path, bbox_inches="tight", dpi=150)
    print(f"> saved: {path}")


def load_data(path):
    df = pd.read_csv(path)
    numeric_cols = [
        "rank", "page", "rating", "review_count", "price_norm",
        "review_density", "norm_review_density",
    ]
    for c in numeric_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    if "price_segment" not in df.columns:
        df["price_segment"] = "unknown"
    df["cat_level_1"] = df["cat_level_1"].fillna("Unknown")
    df["cat_level_2"] = df["cat_level_2"].fillna("")
    df = df[df["price_segment"].notna() & (df["price_segment"].str.lower() != "unknown")]
    return df


def price_segment_distribution(df, group_col="cat_level_1"):
    overall = (
        df["price_segment"].value_counts(normalize=True).rename("share")
        .reset_index().rename(columns={"index": "price_segment"})
    )
    by_cat = df.groupby([group_col, "price_segment"]).size().reset_index(name="count")
    total_by_cat = df.groupby(group_col).size().reset_index(name="cat_total")
    by_cat = by_cat.merge(total_by_cat, on=group_col)
    by_cat["share_in_cat"] = by_cat["count"] / by_cat["cat_total"]
    return overall, by_cat


def main():
    global OUT_DIR
    best_path = sys.argv[1] if len(sys.argv) > 1 else _default_best_path()
    OUT_DIR = os.path.join("outputs", _run_id_from_path(best_path))
    os.makedirs(OUT_DIR, exist_ok=True)
    best = load_data(best_path)
    print(f"Loaded best: {best.shape}  <- {best_path}")
    print(f"输出目录: {OUT_DIR}")

    # ---- Q1: 价格分段分布 ----
    overall_seg, by_cat_seg = price_segment_distribution(best, group_col="cat_level_1")
    overall_seg.to_csv(os.path.join(OUT_DIR, "best_price_segment_overall.csv"), index=False)
    by_cat_seg.to_csv(os.path.join(OUT_DIR, "best_price_segment_by_category.csv"), index=False)

    fig, ax = plt.subplots(figsize=(6, 4))
    overall_seg.plot(kind="bar", x="price_segment", y="share", legend=False, ax=ax, color="#4C72B0")
    ax.set_title("Best Sellers: Price Segment Share (Overall)", fontsize=12, pad=10)
    ax.set_ylabel("Share", fontsize=10)
    ax.set_xlabel("Price Segment", fontsize=10)
    ax.set_ylim(0, overall_seg["share"].max() * 1.2)
    for i, v in enumerate(overall_seg["share"]):
        ax.text(i, v + 0.01, f"{v:.1%}", ha="center", va="bottom",
                fontsize=9, fontweight="bold", color="#333")
    plt.tight_layout()
    save_fig(fig, "best_price_segment_overall.png")
    plt.close(fig)

    top_cats = best["cat_level_1"].value_counts().head(12).index.tolist()
    by_cat_pivot = (
        by_cat_seg[by_cat_seg["cat_level_1"].isin(top_cats)]
        .pivot(index="cat_level_1", columns="price_segment", values="share_in_cat")
        .fillna(0)
    )
    fig, ax = plt.subplots(figsize=(10, 6))
    by_cat_pivot.plot(kind="bar", stacked=True, ax=ax)
    ax.set_title("Best Sellers: Price Segment Share by Top Categories (Top 12)")
    ax.set_ylabel("Share within category")
    ax.set_xlabel("Category")
    plt.xticks(rotation=45, ha="right")
    save_fig(fig, "best_price_segment_by_top_cats.png")
    plt.close(fig)

    # ---- Q2: 评论密度 vs 排名 ----
    df_corr = best.loc[best["review_density"].notna() & best["rank"].notna()].copy()
    spearman = df_corr[["review_density", "rank"]].corr(method="spearman").iloc[0, 1]
    pearson = df_corr[["review_density", "rank"]].corr(method="pearson").iloc[0, 1]
    print(f"Correlation review_density vs rank -> Spearman: {spearman:.4f}, Pearson: {pearson:.4f}")

    df_corr["log_review_density"] = np.log1p(df_corr["review_density"])
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.scatter(df_corr["log_review_density"], df_corr["rank"], alpha=0.6, s=8)
    ax.set_xlabel("log(1 + review_density)")
    ax.set_ylabel("rank (lower is better)")
    ax.set_title("Best Sellers: log(review_density) vs rank")
    save_fig(fig, "best_reviewdensity_vs_rank.png")
    plt.close(fig)

    df_corr["density_q"] = pd.qcut(
        df_corr["norm_review_density"].fillna(0), q=5, duplicates="drop"
    )
    rank_by_q = (
        df_corr.groupby("density_q")["rank"].median()
        .reset_index().rename(columns={"rank": "median_rank"})
    )
    rank_by_q.to_csv(os.path.join(OUT_DIR, "best_rank_by_review_density_quantile.csv"), index=False)

    print("\nDone. 输出已写入", OUT_DIR)


if __name__ == "__main__":
    main()
