# 亚马逊畅销榜选品数据分析（Amazon Best Sellers Selection Analysis）

采集亚马逊全类目畅销榜商品数据，分析价格分层与评论密度对排名的影响，为选品与定价提供数据依据。

## 项目简介

针对「新品定价、评论投入靠经验拍板」的问题，本项目自动抓取亚马逊全类目畅销榜，清洗后按价格分位与评论密度做分层分析，输出价格结构、品类对比、评论密度等图表，形成可复用的选品分析流程。

## 基于的开源项目

本项目基于 [nikoprabowo/amazon-scraped-data-analysis-v1](https://github.com/nikoprabowo/amazon-scraped-data-analysis-v1)（MIT License）二次开发。

## 与原项目的主要区别

| 维度 | 原项目 | 本项目 |
|---|---|---|
| 形态 | 需手动填写 XPath 的 Jupyter Notebook 探索脚本 | 抓取 → 清洗 → 出图一条命令跑通的流水线 |
| 配置 | 无 | 新增 `config.ini`，品类 / 翻页 / 代理 / 无头均配置化 |
| 清洗 | 无兜底 | 从链接反推品类、按榜单页序重排名次，修正错标与断号 |
| 范围 | 畅销榜 + 飙升榜两套脚本 | 聚焦畅销榜，剔除飙升榜冗余脚本 |
| 出图 | ipynb 内嵌出图 | 独立 `analysis.py` 命令行出图 |

## 分析维度

- 价格分层：按品类内分位划低 / 中 / 高三档，定位更具竞争力的价格带
- 评论密度：按评论密度分位分层，量化评论积累对畅销排名的拉动
- 品类结构：跨品类价格结构对比，辅助判断品类机会

## 快速开始

```bash
pip install -r requirements.txt
# 编辑 config.ini（品类、代理、翻页等）
python scripts/scrape_best_sellers_all_category.py   # 抓取
python scripts/transform_best_sellers.py             # 清洗
python scripts/analysis.py                           # 分析出图
```

## 项目结构

```
├── config.ini           # 爬虫配置
├── requirements.txt     # 依赖
├── scripts/
│   ├── scrape_best_sellers_all_category.py  # 抓取畅销榜
│   ├── transform_best_sellers.py            # 清洗与派生字段
│   ├── analysis.py                          # 分析与出图
│   └── parse_html.py                        # 备用：解析手动保存的 HTML
└── data/ outputs/      # 运行产物（不提交）
```

## License

本项目在原项目 [nikoprabowo/amazon-scraped-data-analysis-v1](https://github.com/nikoprabowo/amazon-scraped-data-analysis-v1) 的 MIT License 下二次开发，保留原版权声明（见 `LICENSE`）。
