# crawl_email_from_papers

一个最小可运行的 Python 工具：给它论文的 arXiv ID、arXiv 链接、PDF 链接、本地 PDF 路径，或者一个按行列出这些输入的 `.txt` 文件，它会下载/读取 PDF，扫描前几页文本并提取邮箱，最后导出为 CSV/JSON。

适合场景：

- 批量找论文作者邮箱
- 从 arXiv 论文首页快速抽作者联系方式
- 对本地保存的论文 PDF 做一次性邮箱整理

## 功能

- 支持输入：
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

### 1. 输入 arXiv ID

```bash
python crawl_email_from_papers.py 2401.12345
```

### 2. 输入多个论文来源

```bash
python crawl_email_from_papers.py \
  2401.12345 \
  https://arxiv.org/abs/2402.00001 \
  ./papers/sample.pdf
```

### 3. 从文本文件批量读取

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

### 4. 指定输出路径

```bash
python crawl_email_from_papers.py 2401.12345 \
  --out results/emails.csv \
  --json-out results/emails.json
```

### 5. 调整扫描页数

```bash
python crawl_email_from_papers.py 2401.12345 --max-pages 5
```

## 输出格式

CSV 字段：

- `input`: 原始输入
- `title`: 从 PDF 前几行粗略推断的标题
- `email_count`: 提取到的邮箱数量
- `emails`: 以 `; ` 分隔的邮箱列表
- `source`: `local` 或下载 URL
- `pdf_path`: 本地 PDF 路径

JSON 会保留更完整的结构化结果。

## 示例输出

```csv
input,title,email_count,emails,source,pdf_path
2401.12345,Example Paper Title,2,alice@uni.edu; bob@lab.org,https://arxiv.org/pdf/2401.12345.pdf,.cache/pdfs/xxxx_paper.pdf
```

## 说明和限制

- 默认策略是扫首页和前几页，所以更偏向提取作者公开邮箱，不会保证覆盖论文正文深处的所有联系方式。
- 对纯扫描版 PDF、图片型 PDF，提取质量取决于 PDF 自带文本层；当前没有集成 OCR。
- 邮箱提取基于规则，偶尔会有误报或漏报，尤其是排版破碎、字符断裂严重的 PDF。

## 快速测试

```bash
python crawl_email_from_papers.py https://arxiv.org/abs/2401.06066 --json-out emails.json
```

运行后会生成默认 `emails.csv`，并把结果打印到标准错误输出，方便直接看每篇论文抽到了哪些邮箱。
