#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
parse_html.py — 解析本地保存的亚马逊畅销榜页面 HTML，产出分号分隔 CSV。

（手动「另存为 HTML」后解析用；全自动抓取请用 scrape_best_sellers_all_category.py）

用法:
    python scripts/parse_html.py [html目录 或 单个html文件]
    # 不传参数时，默认读取 ./html 目录下所有 .html/.htm 文件

产出:
    data/parse_best_sellers_all_category.csv
"""

import os
import re
import sys
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# =====================================================================
# 选择器配置：亚马逊页面改版时，只需改下面这些选择器
# =====================================================================
CONFIG = {
    "card": "div#gridItemRoot",
    "category": "div#zg_listTitle, h1, #wayfinding-breadcrumbs_container",
    "title": "div[class*='line-clamp'], div[class*='truncate']",
    "link": "a[href*='/dp/']",
    "rating": "[aria-label*='out of 5 stars'], span.a-icon-alt",
    "reviews": "a[href*='product-reviews'], a[href*='#customerReviews']",
    "price": "span.a-price > span.a-offscreen, span[class*='p13n-sc-price'], span.a-price",
}

ASIN_RE = re.compile(r"/(?:dp|gp/product)/([A-Z0-9]{10})")


def _text(el):
    return el.get_text(" ", strip=True) if el else ""


def _first(soup_or_el, selector):
    try:
        return soup_or_el.select_one(selector)
    except Exception:
        return None


def _extract_category(soup):
    # 优先从 <title> 的 "in <品类>" 提取真实品类名（如 "The most popular items in Baby" -> "Baby"）
    t = soup.title
    if t:
        title = t.get_text(" ", strip=True)
        m = re.search(r"\bin\s+(.+)$", title, flags=re.IGNORECASE)
        if m:
            return m.group(1).strip()
    # 兜底：面包屑（并过滤掉通用 "Amazon Best Sellers" 占位）
    el = _first(soup, "#wayfinding-breadcrumbs_container")
    if el:
        txt = _text(el)
        if txt and txt.strip().lower() != "amazon best sellers":
            return txt
    return None


def _extract_page(soup):
    c = _first(soup, "link[rel='canonical']")
    if c:
        url = c.get("href", "")
        m = re.search(r"zgbs[^?#]*[?&]pg=(\d+)", url)
        if m:
            return int(m.group(1))
        m = re.search(r"zgbs[^?#]*pg[_](\d+)", url)
        if m:
            return int(m.group(1))
    return 1


def _extract_field(card, key):
    el = _first(card, CONFIG[key])
    if key == "rating":
        return (el.get("aria-label") or _text(el)) if el else ""
    if key == "link":
        return el.get("href", "") if el else ""
    return _text(el)


def _parse_card(card, idx, page, category):
    link = _extract_field(card, "link")
    title = _extract_field(card, "title")
    # 标题兜底：用第一个「有文字」的商品链接（图片链接没有文字，要跳过）
    if not title and link:
        for a in card.select(CONFIG["link"]):
            txt = _text(a)
            if txt:
                title = txt
                break

    rating = _extract_field(card, "rating")

    reviews = _extract_field(card, "reviews")
    if not reviews:
        r_el = _first(card, CONFIG["rating"])
        if r_el:
            parent = r_el.parent
            for _ in range(4):
                if parent and re.search(r"\d", _text(parent)):
                    reviews = _text(parent)
                    break
                parent = parent.parent if parent else None
    # 评论数常混在评分文字里（如 "4.4 颗星，最多 5 颗星 280,340"），取末尾的数字
    if reviews:
        nums = re.findall(r"[\d,]+", reviews)
        if nums:
            reviews = nums[-1]

    price = _extract_field(card, "price")

    return {
        "rank": idx,
        "page": page,
        "category": category,
        "title": title,
        "link": link,
        "rating": rating,
        "review_count": reviews,
        "price": price,
    }


def parse_file(path):
    with open(path, "rb") as f:
        html = f.read()
    soup = BeautifulSoup(html, "lxml")

    category = _extract_category(soup)
    page = _extract_page(soup)

    cards = soup.select(CONFIG["card"])
    rows = []
    for idx, card in enumerate(cards, start=1):
        try:
            rows.append(_parse_card(card, idx, page, category))
        except Exception:
            continue

    # 兜底：没找到卡片时，用页面里的 /dp/ 商品链接反向提取
    if not rows:
        seen = set()
        for a in soup.select("a[href*='/dp/']"):
            href = a.get("href", "")
            m = ASIN_RE.search(href)
            if not m or m.group(1) in seen:
                continue
            seen.add(m.group(1))
            rows.append(
                {
                    "rank": len(rows) + 1,
                    "page": page,
                    "category": category,
                    "title": _text(a),
                    "link": href,
                    "rating": "",
                    "review_count": "",
                    "price": "",
                }
            )

    return rows


def _csv_safe(value):
    """防止 CSV 公式注入：以 = + - @ 制表符/回车 开头的字符串加单引号前缀。"""
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + value
    return value


def _sanitize_rows(rows):
    for row in rows:
        for k, v in row.items():
            row[k] = _csv_safe(v)
    return rows


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else "html"
    p = Path(arg)
    files = sorted(list(p.glob("*.html")) + list(p.glob("*.htm"))) if p.is_dir() else [p]

    if not files:
        print(f"未找到 HTML 文件：{arg}")
        sys.exit(1)

    all_rows = []
    for fp in files:
        rows = parse_file(fp)
        filled = sum(1 for r in rows if r["title"] or r["link"])
        print(f"[best_sellers] {fp.name}: 卡片 {len(rows)} 个，有效 {filled} 个")
        if rows:
            s = rows[0]
            print(f"          样例 → 标题: {s['title'][:40]!r} | 价格: {s['price']!r} | 评分: {s['rating'][:20]!r}")
        all_rows.extend(rows)

    os.makedirs("data", exist_ok=True)
    out = "data/parse_best_sellers_all_category.csv"
    pd.DataFrame(_sanitize_rows(all_rows)).to_csv(out, sep=";", index=False)
    print(f"\n畅销榜已保存: {out}（{len(all_rows)} 行）")


if __name__ == "__main__":
    main()
