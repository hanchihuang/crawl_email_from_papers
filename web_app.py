#!/usr/bin/env python3
"""Local web UI for campaign sends."""
import argparse
import html
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from send_emails import (
    DEFAULT_FREEMAIL_ENV,
    DEFAULT_ITICK_POOL,
    HTML_TEMPLATE,
    PLAIN_TEMPLATE,
    SenderPool,
    build_campaign_sender,
    filter_sender_pool_by_domain,
    load_freemail_config,
    load_sender_pool,
    sender_email_domain,
    send_campaign,
)
from src.utils.config import cfg


DEFAULT_SUBJECT = "Research Collaboration Opportunity in Quantitative Finance"
JOB_LOCK = threading.Lock()
JOBS: dict[str, dict] = {}


def html_to_plain_text(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _checked(values: dict, key: str) -> str:
    return "checked" if values.get(key) else ""


def _selected(values: dict, key: str, expected: str) -> str:
    return "selected" if values.get(key, "") == expected else ""


def render_page(values: dict, message: str = "", logs: str = "") -> str:
    msg_html = f'<div id="statusBox" class="message">{html.escape(message)}</div>'
    logs_text = html.escape(logs)
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Email Campaign</title>
  <style>
    :root {{
      --bg: #f1efe7;
      --card: #fffdf8;
      --ink: #20201c;
      --accent: #0d6c63;
      --line: #d7d0bf;
      --muted: #66695f;
    }}
    body {{ margin: 0; font-family: Georgia, "Noto Serif SC", serif; background: linear-gradient(160deg, #f7f3e8, #e5efe8); color: var(--ink); }}
    .wrap {{ max-width: 980px; margin: 32px auto; padding: 0 20px; }}
    .card {{ background: var(--card); border: 1px solid var(--line); border-radius: 20px; padding: 28px; box-shadow: 0 18px 50px rgba(0,0,0,.06); }}
    h1 {{ margin: 0 0 8px; font-size: 32px; }}
    .sub {{ margin: 0 0 24px; color: #5a5c54; }}
    .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
    label {{ display: block; font-size: 14px; margin-bottom: 6px; }}
    input[type="text"], input[type="number"], select, textarea {{
      width: 100%; box-sizing: border-box; border: 1px solid var(--line); border-radius: 12px;
      padding: 12px 14px; font: inherit; background: white;
    }}
    textarea {{ min-height: 180px; resize: vertical; }}
    .full {{ grid-column: 1 / -1; }}
    .row {{ display: flex; gap: 18px; flex-wrap: wrap; margin-top: 8px; }}
    .row label {{ display: inline-flex; align-items: center; gap: 8px; margin: 0; }}
    button {{ background: var(--accent); color: white; border: 0; border-radius: 999px; padding: 12px 22px; font: inherit; cursor: pointer; }}
    button[disabled] {{ opacity: .6; cursor: wait; }}
    .message {{ margin-bottom: 16px; padding: 14px 16px; border-radius: 12px; background: #e8f5f0; border: 1px solid #b7d7cc; white-space: pre-wrap; }}
    .hint {{ font-size: 13px; color: var(--muted); margin-top: 6px; }}
    .meta {{ margin-top: 14px; font-size: 13px; color: var(--muted); }}
    .logbox {{ min-height: 280px; font-family: "SFMono-Regular", Consolas, "Liberation Mono", monospace; }}
    @media (max-width: 800px) {{ .grid {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="card">
      <h1>群发控制台</h1>
      <p class="sub">网页端填写标题和内容，点击后后台执行并实时刷新进度日志。</p>
      {msg_html}
      <form id="campaignForm" method="post" action="/start">
        <div class="grid">
          <div>
            <label>邮件标题</label>
            <input type="text" name="subject" value="{html.escape(values.get("subject", ""))}">
          </div>
          <div>
            <label>发件名称</label>
            <input type="text" name="from_name" value="{html.escape(values.get("from_name", ""))}">
          </div>
          <div>
            <label>发送后端</label>
            <select name="backend">
              <option value="freemail" {_selected(values, "backend", "freemail")}>freemail</option>
              <option value="smtp" {_selected(values, "backend", "smtp")}>smtp</option>
            </select>
          </div>
          <div>
            <label>最大发送数</label>
            <input type="number" name="max_emails" min="0" value="{html.escape(values.get("max_emails", "0"))}">
          </div>
          <div>
            <label>从第几个邮箱开始</label>
            <input type="number" name="start_email_index" min="1" value="{html.escape(values.get("start_email_index", "1"))}">
          </div>
          <div>
            <label>发送间隔（秒）</label>
            <input type="number" name="delay" min="0" value="{html.escape(values.get("delay", "5"))}">
          </div>
          <div>
            <label>发件池 CSV</label>
            <input type="text" name="from_pool_path" value="{html.escape(values.get("from_pool_path", str(DEFAULT_ITICK_POOL)))}">
          </div>
          <div class="full">
            <label>纯文本正文</label>
            <textarea name="body">{html.escape(values.get("body", ""))}</textarea>
          </div>
          <div class="full">
            <label>HTML 正文</label>
            <textarea name="html_body">{html.escape(values.get("html_body", ""))}</textarea>
            <div class="hint">留空时将使用纯文本正文自动生成简单版本。</div>
          </div>
          <div class="full">
            <label>执行日志</label>
            <textarea id="logBox" class="logbox" readonly>{logs_text}</textarea>
            <div id="jobMeta" class="meta"></div>
          </div>
        </div>
        <div class="row">
          <label><input type="checkbox" name="dry_run" {_checked(values, "dry_run")}> dry-run</label>
          <label><input type="checkbox" name="from_pool" {_checked(values, "from_pool")}> 使用 itick 发件池</label>
        </div>
        <div class="row" style="margin-top:20px;">
          <button id="submitBtn" type="submit">执行群发</button>
        </div>
      </form>
    </div>
  </div>
  <script>
    const form = document.getElementById("campaignForm");
    const statusBox = document.getElementById("statusBox");
    const logBox = document.getElementById("logBox");
    const submitBtn = document.getElementById("submitBtn");
    const jobMeta = document.getElementById("jobMeta");
    let pollTimer = null;

    function setRunning(running) {{
      submitBtn.disabled = running;
      submitBtn.textContent = running ? "群发进行中..." : "执行群发";
    }}

    function renderJob(data) {{
      statusBox.textContent = data.message || "";
      logBox.value = (data.logs || []).join("\\n");
      logBox.scrollTop = logBox.scrollHeight;
      jobMeta.textContent = data.job_id ? `任务: ${{data.job_id}} | 状态: ${{data.status}}` : "";
      if (data.status === "completed" || data.status === "failed") {{
        setRunning(false);
        if (pollTimer) {{
          clearInterval(pollTimer);
          pollTimer = null;
        }}
      }}
    }}

    async function pollJob(jobId) {{
      const response = await fetch(`/status?job_id=${{encodeURIComponent(jobId)}}`, {{
        headers: {{ "Accept": "application/json" }}
      }});
      const data = await response.json();
      renderJob(data);
    }}

    form.addEventListener("submit", async (event) => {{
      event.preventDefault();
      if (pollTimer) {{
        clearInterval(pollTimer);
        pollTimer = null;
      }}
      setRunning(true);
      statusBox.textContent = "任务已提交，正在启动...";
      logBox.value = "";
      jobMeta.textContent = "";

      const response = await fetch("/start", {{
        method: "POST",
        body: new FormData(form),
        headers: {{ "Accept": "application/json" }}
      }});
      const data = await response.json();
      renderJob(data);
      if (data.job_id && data.status === "running") {{
        pollTimer = setInterval(() => {{
          pollJob(data.job_id).catch((error) => {{
            statusBox.textContent = `状态拉取失败: ${{error.message}}`;
            setRunning(false);
            clearInterval(pollTimer);
            pollTimer = null;
          }});
        }}, 1000);
      }} else {{
        setRunning(false);
      }}
    }});
  </script>
</body>
</html>"""


def default_form_values() -> dict:
    return {
        "subject": DEFAULT_SUBJECT,
        "body": PLAIN_TEMPLATE,
        "html_body": HTML_TEMPLATE,
        "backend": "freemail",
        "max_emails": "0",
        "start_email_index": "1",
        "delay": "5",
        "from_name": "Quant Finance Research",
        "from_pool": "on",
        "dry_run": "on",
        "from_pool_path": str(DEFAULT_ITICK_POOL),
    }


def merge_form_values(parsed: dict) -> dict:
    values = default_form_values()
    values.update(parsed)
    for key in ("dry_run", "from_pool"):
        if key not in parsed:
            values.pop(key, None)
    return values


def parse_form_body(content_type: str, raw_body: bytes) -> dict:
    if "multipart/form-data" in content_type:
        values: dict[str, str] = {}
        boundary_match = re.search(r"boundary=([^;]+)", content_type)
        if not boundary_match:
            return values
        boundary = boundary_match.group(1).strip().strip('"')
        delimiter = f"--{boundary}".encode("utf-8")
        for part in raw_body.split(delimiter):
            part = part.strip()
            if not part or part == b"--":
                continue
            if b"\r\n\r\n" not in part:
                continue
            header_block, value_block = part.split(b"\r\n\r\n", 1)
            headers = header_block.decode("utf-8", errors="ignore")
            name_match = re.search(r'name="([^"]+)"', headers)
            if not name_match:
                continue
            value = value_block.rstrip(b"\r\n-").decode("utf-8", errors="ignore")
            values[name_match.group(1)] = value
        return values

    decoded = raw_body.decode("utf-8")
    return {key: values[-1] for key, values in parse_qs(decoded, keep_blank_values=True).items()}


def snapshot_job(job_id: str) -> dict:
    with JOB_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return {
                "job_id": job_id,
                "status": "missing",
                "message": "任务不存在",
                "logs": [],
            }
        return {
            "job_id": job_id,
            "status": job["status"],
            "message": job["message"],
            "logs": list(job["logs"]),
        }


def _update_job(job_id: str, **fields) -> None:
    with JOB_LOCK:
        job = JOBS[job_id]
        job.update(fields)


def append_job_log(job_id: str, level: str, message: str) -> None:
    with JOB_LOCK:
        job = JOBS[job_id]
        job["logs"].append(f"{level} | {message}")


def smtp_config_dict() -> dict:
    return {
        "host": cfg.SMTP_HOST,
        "port": cfg.SMTP_PORT,
        "user": cfg.SMTP_USER,
        "password": cfg.SMTP_PASSWORD,
    }


def smtp_is_configured() -> bool:
    return bool(cfg.SMTP_HOST and cfg.SMTP_PORT and cfg.SMTP_USER and cfg.SMTP_PASSWORD)


def freemail_is_configured(config: dict) -> bool:
    return bool(config.get("api_url") and config.get("api_key"))


def run_campaign_from_form(values: dict, progress_callback=None) -> tuple[str, list[str]]:
    backend = values.get("backend", "freemail")
    dry_run = bool(values.get("dry_run"))
    from_pool_enabled = bool(values.get("from_pool"))
    max_emails = int(values.get("max_emails", "0") or "0")
    start_email_index = max(1, int(values.get("start_email_index", "1") or "1"))
    delay = int(values.get("delay", "5") or "5")
    log_lines: list[str] = []

    def capture_log(level: str, message: str):
        line = f"{level} | {message}"
        log_lines.append(line)
        if progress_callback:
            progress_callback(level, message)

    freemail_config = load_freemail_config(DEFAULT_FREEMAIL_ENV)
    smtp_config = smtp_config_dict()
    sender_pool = None
    if from_pool_enabled:
        emails = load_sender_pool(Path(values.get("from_pool_path", str(DEFAULT_ITICK_POOL))))
        if not emails:
            raise ValueError("发件池没有可用邮箱")
        allowed_domains = {sender_email_domain(freemail_config.get("from_email", ""))}
        filtered_emails, rejected_emails = filter_sender_pool_by_domain(emails, allowed_domains)
        if rejected_emails:
            rejected_domains = sorted({sender_email_domain(email) or "invalid" for email in rejected_emails})
            capture_log(
                "WARNING",
                "发件池已过滤不匹配域名的地址: "
                + ", ".join(rejected_domains)
                + f"；仅允许域名: {', '.join(sorted(domain for domain in allowed_domains if domain))}",
            )
        if filtered_emails:
            sender_pool = SenderPool(filtered_emails)
        else:
            capture_log("WARNING", "发件池中没有与当前 freemail 域名匹配的地址，回退到默认发件邮箱")

    if backend == "freemail" and not freemail_is_configured(freemail_config):
        if smtp_is_configured():
            capture_log("WARNING", "freemail 配置不可用，自动切换到 SMTP")
            backend = "smtp"
        else:
            raise ValueError("freemail 未正确配置，且本地 SMTP 也未配置，无法真实发送")

    if backend == "smtp" and not smtp_is_configured():
        if freemail_is_configured(freemail_config):
            capture_log("WARNING", "SMTP 未配置，自动切换到 freemail")
            backend = "freemail"
        else:
            raise ValueError("SMTP 未配置，且 freemail 也不可用，无法真实发送")

    sender, meta = build_campaign_sender(
        backend=backend,
        smtp_config=smtp_config,
        freemail_config=freemail_config,
        sender_pool=sender_pool,
    )

    html_body = values.get("html_body") or f"<pre>{html.escape(values.get('body', ''))}</pre>"
    result = send_campaign(
        sender=sender,
        authors_file=cfg.AUTHOR_DATA_FILE,
        backend_name=meta["backend"],
        from_name=values.get("from_name") or freemail_config.get("from_name") or "Quant Finance Research",
        sender_pool=sender_pool,
        start_index=start_email_index,
        max_emails=max_emails,
        delay=delay,
        dry_run=dry_run,
        subject_template=values.get("subject") or DEFAULT_SUBJECT,
        plain_template=values.get("body") or html_to_plain_text(html_body),
        html_template=html_body,
        progress_callback=capture_log,
    )
    if (
        not dry_run
        and result["sent"] == 0
        and result["failed"] > 0
        and any("未配置 Resend API Key" in line for line in log_lines)
    ):
        if backend == "freemail" and smtp_is_configured():
            capture_log("WARNING", "freemail 后端未配置 Resend，自动回退到 SMTP 重新尝试")
            sender, meta = build_campaign_sender(
                backend="smtp",
                smtp_config=smtp_config,
                freemail_config=freemail_config,
                sender_pool=None,
            )
            result = send_campaign(
                sender=sender,
                authors_file=cfg.AUTHOR_DATA_FILE,
                backend_name=meta["backend"],
                from_name=values.get("from_name") or freemail_config.get("from_name") or "Quant Finance Research",
                sender_pool=None,
                max_emails=max_emails,
                delay=delay,
                dry_run=dry_run,
                subject_template=values.get("subject") or DEFAULT_SUBJECT,
                plain_template=values.get("body") or html_to_plain_text(html_body),
                html_template=html_body,
                progress_callback=capture_log,
            )
            backend = "smtp"
        elif backend == "freemail":
            raise ValueError("freemail 后端未配置 Resend API Key，且本地 SMTP 未配置，当前无法真实发送")
    mode = "DRY RUN" if dry_run else "LIVE"
    message = (
        f"{mode} completed with backend={backend}, "
        f"sent={result['sent']}, failed={result['failed']}, remaining={result['remaining']}"
    )
    return message, log_lines


def create_job(values: dict) -> str:
    job_id = uuid4().hex[:12]
    with JOB_LOCK:
        JOBS[job_id] = {
            "status": "running",
            "message": "任务已创建，等待发送日志...",
            "logs": [],
            "values": values,
        }
    thread = threading.Thread(target=_run_job, args=(job_id,), daemon=True)
    thread.start()
    return job_id


def _run_job(job_id: str) -> None:
    with JOB_LOCK:
        values = dict(JOBS[job_id]["values"])
    try:
        message, _ = run_campaign_from_form(
            values,
            progress_callback=lambda level, text: append_job_log(job_id, level, text),
        )
        _update_job(job_id, status="completed", message=message)
    except Exception as exc:
        append_job_log(job_id, "ERROR", str(exc))
        _update_job(job_id, status="failed", message=f"执行失败: {exc}")


class CampaignHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/status":
            query = parse_qs(parsed.query)
            job_id = (query.get("job_id") or [""])[0]
            self._write_json(snapshot_job(job_id), status=200 if job_id else 400)
            return
        self._write_html(render_page(default_form_values()))

    def do_POST(self):
        parsed_url = urlparse(self.path)
        length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(length)
        parsed = parse_form_body(self.headers.get("Content-Type", ""), raw_body)
        values = merge_form_values(parsed)

        if parsed_url.path == "/start":
            try:
                job_id = create_job(values)
                self._write_json(snapshot_job(job_id))
            except Exception as exc:
                self._write_json({"status": "failed", "message": f"执行失败: {exc}", "logs": []}, status=500)
            return

        logs = []
        try:
            message, logs = run_campaign_from_form(values)
        except Exception as exc:
            message = f"执行失败: {exc}"
        self._write_html(render_page(values, message, "\n".join(logs)))

    def log_message(self, format, *args):
        return

    def _write_html(self, body: str):
        encoded = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _write_json(self, payload: dict, status: int = 200):
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def parse_args():
    parser = argparse.ArgumentParser(description="Run the local email campaign web UI")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host")
    parser.add_argument("--port", type=int, default=8080, help="Bind port")
    return parser.parse_args()


def main():
    args = parse_args()
    server = ThreadingHTTPServer((args.host, args.port), CampaignHandler)
    print(f"Open http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
