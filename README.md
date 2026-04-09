# Quant Finance Email Crawler

自动从多个学术来源抓取量化金融论文，提取作者邮箱，并支持一键自动发邮件，用于科研合作 outreach。

## 当前已启用的数据源

| 来源 | 说明 | 状态 |
|------|------|------|
| arXiv | 量化金融 (q-fin.*)、经济学 (econ.GN) 分类 | 已启用 |
| Crossref | 学术论文元数据与 DOI 检索 | 已启用 |
| Google Scholar | 作为邮箱补充查找渠道，不是主抓取源 | 辅助启用 |

说明：

- `SSRN` 和 `RePEc` 代码文件目前存在，但默认没有加入实际运行管线
- README 以下说明均以“当前默认启用 arXiv + Crossref”为准

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境

```bash
cp .env.example .env
# 编辑 .env，填入 SMTP 配置
```

SMTP 推荐使用 Gmail + App Password，或 SendGrid / AWS SES。

### 3. 运行爬虫

```bash
# 默认抓取（每个源最多 100 篇，不下载 PDF）
python run_crawler.py

# 增加论文数量
python run_crawler.py --max-papers 200

# 下载 PDF 并从中提取邮箱
python run_crawler.py --max-papers 100

# 强制清理已下载的论文
python run_crawler.py --force-cleanup

# 查看磁盘使用
python run_crawler.py --check-disk
```

### 4. 发送邮件

```bash
# 先 dry-run 查看效果
python send_emails.py --dry-run --max 10

# 确认无误后正式发送
python send_emails.py --live --max 50
```

### 4.1 一键发送邮件

项目已经内置两种“一键发送”方式：

```bash
# 命令行一键群发
python send_emails.py --live --max 50

# 启动本地网页控制台，一键点击执行群发
python web_app.py
```

启动 `web_app.py` 后，在浏览器打开页面，填好标题、正文、发送后端和数量，点击“执行群发”即可。

支持：

- `SMTP` 直连发送
- `freemail` API 发送
- `dry-run` 预演
- 发件池轮换发送

如果只想先测试流程，建议先执行：

```bash
python send_emails.py --dry-run --max 10
```

### 4.2 一键 push GitHub

当前目录默认不是 Git 仓库；如果你要把这个项目一键推到 GitHub，先完成一次初始化或接入已有远端。

首次初始化示例：

```bash
git init
git branch -M main
git remote add origin https://github.com/<your-name>/quant_finance_email_crawler.git
```

之后可直接用一条命令完成 add、commit、push：

```bash
git add . && git commit -m "update quant_finance_email_crawler" && git push -u origin main
```

如果已经配置过远端，后续日常更新只需要：

```bash
git add . && git commit -m "update" && git push
```

## 工作流程

```
1. 爬虫抓取论文元数据 (标题/作者/摘要/URL)
       ↓
2. 从论文页面 + PDF 提取作者邮箱
       ↓
3. 邮箱去重后存入 data/authors/authors.json
       ↓
4. PDF 下载后立即自动删除 (默认开启)
       ↓
5. 从 authors.json 读取作者列表发送邮件
```

## 邮箱提取策略

1. **论文元数据** - 从当前已启用来源（默认是 arXiv / Crossref）的 abstract 和 author 字段中搜索邮箱正则
2. **论文详情页** - 抓取 HTML 页面，用 BeautifulSoup 提取 `mailto:` 链接
3. **arXiv 作者页** - 访问 arXiv 作者主页查找邮箱
4. **Scholarly API** - 对每个作者名搜索 Google Scholar，找关联邮箱
5. **PDF 正文** - 下载 PDF 用 pdftotext 提取全文，再正则匹配邮箱

> 策略 1-3 不下载 PDF，最快；策略 5 需要下载 PDF。

## 邮件发送频率控制

- 默认每小时最多 50 封 (MAX_EMAILS_PER_HOUR)
- 每封邮件间隔 3-8 秒随机延迟
- 支持 Gmail/App Password、SMTP relay、SendGrid 等任何 SMTP 服务

## 文件结构

```
quant_finance_email_crawler/
├── run_crawler.py          # 主入口：运行爬虫
├── send_emails.py          # 命令行一键邮件发送
├── web_app.py              # 本地网页群发控制台
├── requirements.txt
├── .env.example            # 配置模板
├── src/
│   ├── scrapers/           # 论文来源爬虫
│   │   ├── arxiv_scraper.py
│   │   ├── crossref_scraper.py
│   │   ├── ssrn_scraper.py         # 代码存在，默认未启用
│   │   └── repec_scraper.py        # 代码存在，默认未启用
│   ├── extractors/         # 邮箱提取
│   │   ├── email_extractor.py
│   │   └── scholarly_client.py
│   ├── emailer/            # 邮件发送
│   │   └── sender.py
│   ├── storage/            # PDF 存储与清理
│   │   └── paper_storage.py
│   ├── utils/
│   │   └── config.py
│   └── crawler.py          # 主编排器
└── data/
    ├── papers/             # 临时 PDF（自动清理）
    ├── authors/
    │   ├── authors.json    # 最终作者+邮箱数据
    │   ├── processed.txt   # 已处理的论文 ID
    │   └── email_queue.json
    └── logs/
        └── crawler.log
```

## 注意事项

- 论文 PDF 下载后默认**立即删除**，节省磁盘空间
- 遵守各平台 robots.txt 和使用条款
- 邮件 outreach 遵守 CAN-SPAM / GDPR 规定
- 建议先用 `--dry-run` 确认邮件内容后再发送
- `push GitHub` 前请先确认当前目录已经 `git init` 并配置好 `origin`
- 当前默认抓取源不是 “arXiv + SSRN + RePEc 全开”，而是以代码实际启用项为准
