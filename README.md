# crawl_email_from_papers

一个先爬论文、再抓作者邮箱的 Python 工具。

核心流程不是“手工指定每篇论文”，而是：

1. 先从 arXiv 按关键词或分类爬取论文列表
2. 自动下载这些论文的 PDF
3. 扫描首页和前几页文本
4. 提取作者公开邮箱
5. 导出 CSV / JSON

另外也保留了“手工补充输入”的能力，方便你对单篇论文或本地 PDF 做补抓。

适合场景：

- 按关键词批量爬论文并整理作者邮箱
- 按 arXiv 分类持续抓取新论文联系人
- 批量找论文作者邮箱
- 对本地保存的论文 PDF 做补充整理

## 功能

- 支持从 arXiv 自动爬论文：
  - 关键词查询，例如 `all:diffusion model`
  - 分类查询，例如 `cat:cs.LG`
  - 可指定抓取数量和起始偏移
- 支持补充显式输入：
  - arXiv ID，例如 `2401.12345`
  - arXiv 摘要页链接，例如 `https://arxiv.org/abs/2401.12345`
  - 直接 PDF 链接
  - 本地 PDF 文件
  - `.txt` 列表文件，一行一个输入
- 自动缓存下载下来的 PDF 到 `.cache/pdfs/`
- 默认只扫描前 3 页，速度更快，也更符合作者邮箱通常出现在首页的实际情况
- 同时处理标准邮箱和常见混淆写法，例如 `name (at) school (dot) edu`
- 输出 `CSV`，可选输出 `JSON`

## 安装

```bash
git clone https://github.com/hanchihuang/crawl_email_from_papers.git
cd crawl_email_from_papers
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

如果你的系统安装了 `pdftotext`，当 `PyMuPDF` 对某些 PDF 提取失败时，脚本会自动回退使用它。

Ubuntu / Debian:

```bash
sudo apt-get update
sudo apt-get install -y poppler-utils
```

## 用法

### 1. 从 arXiv 自动爬论文再抓邮箱

```bash
python crawl_email_from_papers.py \
  --query 'cat:cs.LG' \
  --max-results 20 \
  --out results/cs_lg_emails.csv
```

### 2. 按关键词爬论文

```bash
python crawl_email_from_papers.py \
  --query 'all:diffusion model' \
  --max-results 10 \
  --json-out results/diffusion.json
```

### 3. 爬虫模式和手工输入混合使用

```bash
python crawl_email_from_papers.py \
  --query 'cat:cs.CL' \
  --max-results 5 \
  ./papers/local_paper.pdf \
  2401.12345
```

### 4. 从文本文件批量读取补充输入

`papers.txt`:

```text
2401.12345
https://arxiv.org/abs/2402.00001
./papers/sample.pdf
```

运行：

```bash
python crawl_email_from_papers.py papers.txt
```

### 5. 指定输出路径

```bash
python crawl_email_from_papers.py --query 'cat:cs.AI' \
  --out results/emails.csv \
  --json-out results/emails.json
```

### 6. 调整扫描页数

```bash
python crawl_email_from_papers.py --query 'cat:cs.LG' --max-results 10 --max-pages 5
```

## 输出格式

CSV 字段：

- `input`: 原始输入
- `paper_id`: 论文 ID，爬虫模式下通常是 arXiv 详情页
- `title`: 论文标题
- `published`: 发布时间
- `email_count`: 提取到的邮箱数量
- `emails`: 以 `; ` 分隔的邮箱列表
- `crawl_source`: 论文来源，当前是 `arxiv`
- `crawl_query`: 本次使用的抓取查询词
- `source`: `local` 或下载 URL
- `pdf_path`: 本地 PDF 路径

JSON 会保留更完整的结构化结果。

## 示例输出

```csv
input,paper_id,title,published,email_count,emails,crawl_source,crawl_query,source,pdf_path
https://arxiv.org/pdf/2401.12345.pdf,https://arxiv.org/abs/2401.12345,Example Paper Title,2024-01-11T00:00:00Z,2,alice@uni.edu; bob@lab.org,arxiv,cat:cs.LG,https://arxiv.org/pdf/2401.12345.pdf,.cache/pdfs/xxxx_paper.pdf
```

## 说明和限制

- 默认主路径是“先爬论文，再抽邮箱”，不是要求你手工逐篇指定。
- 当前自动爬取来源先接了 arXiv；如果你后面要接 ACL Anthology、OpenReview、Semantic Scholar，再往上加源就行。
- 默认策略是扫首页和前几页，所以更偏向提取作者公开邮箱，不会保证覆盖论文正文深处的所有联系方式。
- 对纯扫描版 PDF、图片型 PDF，提取质量取决于 PDF 自带文本层；当前没有集成 OCR。
- 邮箱提取基于规则，偶尔会有误报或漏报，尤其是排版破碎、字符断裂严重的 PDF。

## 快速测试

```bash
python crawl_email_from_papers.py \
  --query 'cat:cs.LG' \
  --max-results 3 \
  --json-out emails.json
```

运行后会先爬到论文，再生成默认 `emails.csv`，并把每篇论文抽到的邮箱打印到标准错误输出。
