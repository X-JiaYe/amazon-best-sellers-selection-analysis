#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scrape_best_sellers_all_category.py — 亚马逊畅销榜爬虫（Selenium 真实浏览器）

自动读取品类 URL 清单，逐个品类实时爬取 Best Sellers 榜，输出分号分隔 CSV。
反爬：自定义 UA + 关闭自动化标志 + Clash 代理换 IP。

用法:
    python scripts/scrape_best_sellers_all_category.py --limit 1   # 只爬前 1 个品类（验证用）
    python scripts/scrape_best_sellers_all_category.py             # 全量
"""

import argparse
import configparser
import glob
import os
import re
import sys
import time

import pandas as pd
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# ===== 选择器（亚马逊页面改版时改这里）=====
CARD = "div#gridItemRoot"
TITLE = "div[class*='line-clamp'], div[class*='truncate']"
LINK = "a[href*='/dp/']"
RATING = "[aria-label*='out of 5 stars'], span.a-icon-alt"
REVIEWS = "a[href*='product-reviews'], a[href*='#customerReviews']"
PRICE = "span.a-price > span.a-offscreen, span[class*='p13n-sc-price']"

INPUT_CSV_GLOB = "data/transf_url_*.csv"  # 品类 URL 清单（按实际文件名匹配，不写死日期后缀）
OUTPUT_CSV = "data/scrape_best_sellers_all_category.csv"
CONFIG_FILE = "config.ini"  # 配置文件（项目根目录；不存在则用默认值）

# 默认配置（config.json 里可覆盖）
DEFAULT_CONFIG = {
    "max_pages_per_category": 10,   # 每品类最多翻页数（抓到没商品为止，此为安全上限）
    "proxy": "127.0.0.1:7897",      # Clash 代理地址
    "headless": False,              # 是否无头运行（调试时设为 false 看浏览器）
    "page_delay_seconds": 2,        # 每页之间的等待秒数
}


def load_config():
    """读取 config.ini；文件缺失或字段缺失时用默认值兜底。"""
    cfg = dict(DEFAULT_CONFIG)
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", CONFIG_FILE)
    if os.path.exists(path):
        try:
            parser = configparser.ConfigParser()
            parser.read(path, encoding="utf-8")
            if parser.has_section("scraper"):
                sec = parser["scraper"]
                if sec.get("max_pages_per_category"):
                    cfg["max_pages_per_category"] = int(sec["max_pages_per_category"])
                if sec.get("proxy"):
                    cfg["proxy"] = sec["proxy"].strip()
                if sec.get("headless"):
                    cfg["headless"] = sec["headless"].strip().lower() in ("1", "true", "yes", "on")
                if sec.get("page_delay_seconds"):
                    cfg["page_delay_seconds"] = float(sec["page_delay_seconds"])
        except Exception as e:
            print(f"读取 {path} 失败，用默认值: {e}")
    return cfg


def setup_driver(proxy=DEFAULT_CONFIG["proxy"], headless=False):
    options = Options()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-geolocation")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    if headless:
        options.add_argument("--headless=new")
    options.add_argument(f"--proxy-server={proxy}")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/141.0.0.0 Safari/537.36"
    )
    return webdriver.Chrome(
        service=Service(ChromeDriverManager().install()), options=options
    )


def _find(el, sel):
    try:
        return el.find_element(By.CSS_SELECTOR, sel)
    except Exception:
        return None


def _find_all(el, sel):
    try:
        return el.find_elements(By.CSS_SELECTOR, sel)
    except Exception:
        return []


def _text(el):
    if el is None:
        return None
    t = el.text
    if not t:
        t = el.get_attribute("textContent")
    return t.strip() if t else None


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


def category_from_url(url):
    """从品类 URL 提取品类名（不依赖页面 DOM，防亚马逊改版）。

    两种路径格式都支持：
      /Best-Sellers-Baby/zgbs/baby-products/ ...
      /best-sellers-video-games/zgbs/videogames/ ...
    """
    m = re.search(r"best-sellers-([^/]+)/zgbs/", url, flags=re.IGNORECASE)
    if m:
        return m.group(1).replace("-", " ").title()
    return url


def scrape_best_sellers(driver, url, page_number, category, global_offset=0):
    print(f"\n Opening {url} ...")
    driver.get(url)
    try:
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, CARD))
        )
    except Exception:
        pass  # 翻到末页时可能没有商品卡片，交给下方 cards 判断返回空列表

    time.sleep(2)  # 等 JS 渲染完整

    cards = _find_all(driver, CARD)
    print(f" Products detected: {len(cards)}")
    if not cards:
        return []

    data = []
    for idx, card in enumerate(cards, start=1):
        title = _text(_find(card, TITLE))
        link_el = _find(card, LINK)
        href = link_el.get_attribute("href") if link_el else None

        rating_el = _find(card, RATING)
        rating = None
        if rating_el:
            rating = rating_el.get_attribute("aria-label") or rating_el.text or None

        review_count = None
        rev_el = _find(card, REVIEWS)
        if rev_el:
            nums = re.findall(r"[\d,]+", rev_el.text or "")
            review_count = nums[-1] if nums else None

        price = _text(_find(card, PRICE))

        data.append(
            {
                "rank": global_offset + idx,
                "page": page_number,
                "category": category,
                "title": title,
                "link": href,
                "rating": rating,
                "review_count": review_count,
                "price": price,
            }
        )
        print(f" #{global_offset + idx:03d} | {(title or '')[:45]} | {price}")

    return data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="只爬前 N 个品类，0=全部")
    args = parser.parse_args()

    cfg = load_config()
    max_pages = int(cfg.get("max_pages_per_category", 10))
    page_delay = float(cfg.get("page_delay_seconds", 2))

    url_files = sorted(glob.glob(INPUT_CSV_GLOB))
    if not url_files:
        print(f"未找到品类 URL 清单：{INPUT_CSV_GLOB}")
        sys.exit(1)
    df_urls = pd.read_csv(url_files[0])
    category_urls = df_urls["transformed_url"].dropna().tolist()
    if args.limit:
        category_urls = category_urls[: args.limit]

    driver = setup_driver(proxy=cfg.get("proxy"), headless=cfg.get("headless", False))
    all_results = []
    try:
        for cat_idx, base_url in enumerate(category_urls, start=1):
            print(f"\n=== Category {cat_idx}/{len(category_urls)} ===")
            category = category_from_url(base_url)
            offset = 0  # 排名偏移按实际抓到的条数累计，不写死每页条数
            page = 1
            while page <= max_pages:  # 按实际结果翻页，直到某页无商品为止（上限见 config.json）
                url = re.sub(r"pg_\d+", f"pg_{page}", base_url)
                url = re.sub(r"pg=\d+", f"pg={page}", url)
                try:
                    results = scrape_best_sellers(driver, url, page, category, offset)
                except Exception as e:
                    print(f"  !! 品类 {cat_idx} 第 {page} 页失败: {e}")
                    time.sleep(page_delay)
                    page += 1
                    continue
                if not results:
                    print(f"  品类 {cat_idx} 第 {page} 页已无商品，停止（本品类共 {offset} 条）")
                    break
                all_results.extend(results)
                offset += len(results)
                page += 1
                time.sleep(page_delay)
    finally:
        driver.quit()

    pd.DataFrame(_sanitize_rows(all_results)).to_csv(OUTPUT_CSV, sep=";", index=False)
    print(f"\nDone. Saved {len(all_results)} rows to {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
