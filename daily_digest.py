# -*- coding: utf-8 -*-
"""
新闻传播学每日文献推送
- 数据源：国家哲学社会科学文献中心（NCPSSD）
- 推荐理由：DeepSeek
- 输出：邮件

首次运行请使用：
python daily_paper_recommend.py --dry-run --skip-deepseek
"""

from __future__ import annotations

import html
import os
import re
import smtplib
import sys
import time
from datetime import date as date_cls
from datetime import datetime, timedelta
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests
from dotenv import load_dotenv


# ---------------- 配置 ----------------

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env")

NCPSSD_BASE_URL = "https://ncpssd.org"
NCPSSD_SEARCH_URL = f"{NCPSSD_BASE_URL}/searchHandler/search"

JOURNALS = [
    "国际新闻界",
    "新闻与传播研究",
    "现代传播",
    "新闻大学",
]

TOPICS = [
    "算法审计",
    "多模态新闻",
    "AI说服",
]

PUSHED_FILE = BASE_DIR / "pushed.txt"
OUTPUT_DIR = BASE_DIR / "digest_output"

RESULT_COUNT = 3
POOL_SIZE = 20
WINDOW_DAYS_TIERS = (30, 90, 365, 100000)

REQUEST_TIMEOUT_SECONDS = 90
REQUEST_DELAY_SECONDS = 1.0
SORT_BY_TIME = "synUpdateType|DESC,date|DESC,ik_subject|DESC,id|DESC"

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
QQ_EMAIL = os.getenv("QQ_EMAIL", "")
QQ_SMTP_CODE = os.getenv("QQ_SMTP_CODE", "")
MAIL_TO = os.getenv("MAIL_TO", "2677562625@qq.com")

DRY_RUN = "--dry-run" in sys.argv
SKIP_DEEPSEEK = "--skip-deepseek" in sys.argv
TODAY = datetime.now().date()


# ---------------- NCPSSD 检索 ----------------

def clean_text(value: Any) -> str:
    """清理 NCPSSD 返回字段中的 HTML、Solr 标记和多余空白。"""
    if value is None:
        return ""

    text = html.unescape(str(value))
    text = re.sub(r"<[^>]*>", "", text)
    text = re.sub(r"\[[^\]]*\]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def split_values(value: Any) -> list[str]:
    """NCPSSD 作者和关键词一般以分号分隔。"""
    text = clean_text(value)
    if not text:
        return []

    return [
        item.strip()
        for item in re.split(r"[;；]", text)
        if item.strip()
    ]


def normalize_journal(value: str) -> str:
    return re.sub(r"[\s()（）]", "", value or "")


def is_target_journal(journal: str) -> bool:
    normalized = normalize_journal(journal)
    return any(
        normalize_journal(target) in normalized
        for target in JOURNALS
    )


def build_expression() -> str:
    """
    使用 NCPSSD 页面实际使用的字段：
    IKTE / IKPYTE / IKST / IKET / IKSE = 题名、拼音题名、关键词、英文题名等
    CNEM = 期刊名称
    TYPE = 文献类型
    """
    topic_conditions = []

    for topic in TOPICS:
        topic_conditions.append(
            "("
            f'IKTE="{topic}" OR '
            f'IKPYTE="{topic}" OR '
            f'IKST="{topic}" OR '
            f'IKET="{topic}" OR '
            f'IKSE="{topic}"'
            ")"
        )

    journal_conditions = [
        f'CNEM="{journal}"'
        for journal in JOURNALS
    ]

    return (
        f'({" OR ".join(topic_conditions)}) '
        f'AND ({" OR ".join(journal_conditions)}) '
        'AND TYPE="中文期刊文章"'
    )


def make_detail_url(row: dict[str, Any]) -> str:
    """NCPSSD 详情页依赖列表返回的 encryptedUrl。"""
    encrypted_url = clean_text(row.get("encryptedUrl"))

    if not encrypted_url:
        return ""

    return (
        f"{NCPSSD_BASE_URL}/Literature/secure/articleinfo"
        f"?params={quote(encrypted_url, safe='')}"
    )


def row_to_article(row: dict[str, Any]) -> dict[str, Any]:
    title = clean_text(row.get("ik_title") or row.get("title"))
    journal = clean_text(row.get("cbw_name"))
    year = clean_text(row.get("years"))
    issue = clean_text(row.get("num"))

    return {
        "id": clean_text(row.get("data_id") or row.get("id")),
        "title": title,
        "authors": split_values(row.get("ik_creator") or row.get("creator")),
        "journal": journal,
        "source": journal,
        "year": year,
        "issue": issue,
        "date": clean_text(
            row.get("date")
            or row.get("publish_date")
            or row.get("pubdate")
            or year
        ),
        "keywords": split_values(row.get("ik_subject")),
        "abstract": clean_text(row.get("remark")),
        "url": make_detail_url(row),
        "type": clean_text(row.get("type")),
    }


def search_ncpssd(limit: int = POOL_SIZE) -> list[dict[str, Any]]:
    query = build_expression()

    payload = {
        "search": query,
        "pageNum": 1,
        "pageSize": limit,
        "sort": SORT_BY_TIME,
        "sType": "0",
        "ajaxKeys": ",".join(TOPICS),
        "customShowCondition": (
            f'题名/关键词="{" OR ".join(TOPICS)}"'
        ),
    }

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Referer": f"{NCPSSD_BASE_URL}/",
        "X-Requested-With": "XMLHttpRequest",
    }

    response = requests.post(
        NCPSSD_SEARCH_URL,
        data=payload,
        headers=headers,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()

    try:
        body = response.json()
    except ValueError as exc:
        raise RuntimeError(
            "NCPSSD 未返回 JSON。"
            f"HTTP {response.status_code}，响应前 500 字符：\n"
            f"{response.text[:500]}"
        ) from exc

    data = body.get("data")
    if not isinstance(data, dict):
        raise RuntimeError(f"NCPSSD 返回结构异常：{body!r}")

    rows = data.get("rows") or []
    if not isinstance(rows, list):
        raise RuntimeError("NCPSSD 返回的 data.rows 不是列表。")

    total = data.get("total", 0)
    print(f"[检索] NCPSSD 匹配总数：{total}，本次获取：{len(rows)} 条")

    articles = [
        row_to_article(row)
        for row in rows
        if isinstance(row, dict)
    ]

    # 即使服务端查询条件发生变化，也在本地再次确认期刊和文献类型。
    articles = [
        article
        for article in articles
        if article["title"]
        and article["type"] == "中文期刊文章"
        and is_target_journal(article["journal"])
    ]

    print(f"[检索] 本地期刊和类型过滤后：{len(articles)} 条")

    if REQUEST_DELAY_SECONDS:
        time.sleep(REQUEST_DELAY_SECONDS)

    return articles


# ---------------- 已推送清单（去重） ----------------

def load_pushed() -> set[str]:
    if not PUSHED_FILE.exists():
        return set()

    return {
        line.strip()
        for line in PUSHED_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }


def add_pushed(titles: list[str]) -> None:
    with PUSHED_FILE.open("a", encoding="utf-8") as file:
        for title in titles:
            file.write(title + "\n")


# ---------------- 日期与选文 ----------------

def parse_date(value: Any) -> date_cls | None:
    """
    优先读取接口可能提供的完整发表日期。
    如果仅有年份，不能准确判断 30/90 天窗口，交给最终兜底窗口处理。
    """
    text = clean_text(value)

    for pattern in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(text[:10], pattern).date()
        except ValueError:
            pass

    match = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日?", text)
    if match:
        year, month, day = map(int, match.groups())
        try:
            return date_cls(year, month, day)
        except ValueError:
            return None

    return None


def pick_top_articles(
    pool: list[dict[str, Any]],
    pushed: set[str],
    chosen: set[str],
    count: int = RESULT_COUNT,
) -> tuple[list[dict[str, Any]], int]:
    """按 NCPSSD 的时间排序取前几篇，时间窗不足时自动放宽。"""
    base = [
        article
        for article in pool
        if article["title"] not in pushed
        and article["title"] not in chosen
    ]

    picked: list[dict[str, Any]] = []
    used_days = WINDOW_DAYS_TIERS[-1]

    for days in WINDOW_DAYS_TIERS:
        cutoff = TODAY - timedelta(days=days)

        picked = [
            article
            for article in base
            if (
                parse_date(article.get("date")) is not None
                and parse_date(article["date"]) >= cutoff
            )
        ][:count]

        if len(picked) >= count:
            used_days = days
            break

    # 有些 NCPSSD 列表记录只提供年份，没有完整日期。
    # 最后仍按服务器的时间排序，从未推送候选中补足。
    if len(picked) < count:
        selected_titles = {article["title"] for article in picked}
        for article in base:
            if article["title"] not in selected_titles:
                picked.append(article)
                selected_titles.add(article["title"])

            if len(picked) >= count:
                break

    print(f"[选文] 时间窗 {used_days} 天，选中 {len(picked)} 篇")
    return picked, used_days


# ---------------- DeepSeek ----------------

def call_deepseek(prompt: str) -> str:
    if not DEEPSEEK_API_KEY:
        raise RuntimeError("未配置 DEEPSEEK_API_KEY。")

    response = requests.post(
        "https://api.deepseek.com/chat/completions",
        headers={
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": "deepseek-chat",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7,
        },
        timeout=60,
    )
    response.raise_for_status()

    return response.json()["choices"][0]["message"]["content"].strip()


def get_reason(article: dict[str, Any]) -> str:
    """让 DeepSeek 生成一句推荐理由。"""
    if SKIP_DEEPSEEK:
        return ""

    title = article.get("title", "")
    keywords = "、".join(article.get("keywords") or [])
    abstract = (article.get("abstract") or "")[:400]

    prompt = (
        "你是新闻传播学领域的研究助理。请用一句话（40 字以内）说明下面这篇论文"
        "为什么值得关注，语气客观、直击要点，不要重复标题。\n\n"
        f"题目：{title}\n"
        f"关键词：{keywords}\n"
        f"摘要：{abstract}\n\n"
        "只返回这一句话，不要任何前缀。"
    )

    try:
        return call_deepseek(prompt)
    except Exception as exc:
        print("DeepSeek 调用失败：", exc)
        return ""


# ---------------- 邮件 ----------------

def escape(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def build_email_html(
    articles: list[dict[str, Any]],
    used_days: int,
) -> str:
    today = datetime.now().strftime("%Y-%m-%d")

    parts = [
        f"<h2>新闻传播学每日文献推送（{today}）</h2>",
        (
            "<p style='color:#888'>"
            f"数据源：国家哲学社会科学文献中心 · "
            f"期刊：{'、'.join(map(escape, JOURNALS))} · "
            f"议题：{'、'.join(map(escape, TOPICS))} · "
            f"时间窗：近 {used_days} 天"
            "</p>"
        ),
    ]

    for index, item in enumerate(articles, start=1):
        article = item["article"]
        reason = item.get("reason", "")

        title = escape(article.get("title"))
        authors = escape("、".join(article.get("authors") or []))
        journal = escape(article.get("journal"))
        year = escape(article.get("year"))
        issue = escape(article.get("issue"))
        keywords = escape("、".join(article.get("keywords") or []))
        abstract = escape(article.get("abstract") or "（无摘要）")
        url = escape(article.get("url"))

        issue_text = f"第 {issue} 期" if issue else ""
        source_text = " ".join(
            item for item in [journal, year, issue_text] if item
        )

        parts.append(f"<h3>{index}. {title}</h3>")
        parts.append(f"<p><b>作者：</b>{authors or '（无）'}</p>")
        parts.append(f"<p><b>期刊：</b>{source_text or '（无）'}</p>")
        parts.append(f"<p><b>关键词：</b>{keywords or '（无）'}</p>")

        if reason:
            parts.append(f"<p><b>推荐理由：</b>{escape(reason)}</p>")

        parts.append(f"<p><b>摘要：</b>{abstract}</p>")

        if url:
            parts.append(
                f'<p><a href="{url}">→ 国家哲学社会科学文献中心详情页</a></p>'
            )

        parts.append("<hr>")

    return "\n".join(parts)


def send_email(subject: str, content_html: str) -> None:
    if not QQ_EMAIL or not QQ_SMTP_CODE:
        raise RuntimeError(
            "未配置 QQ_EMAIL 或 QQ_SMTP_CODE，无法发送邮件。"
        )

    message = MIMEText(content_html, "html", "utf-8")
    message["From"] = formataddr(("每日文献推送", QQ_EMAIL))
    message["To"] = MAIL_TO
    message["Subject"] = Header(subject, "utf-8")

    with smtplib.SMTP_SSL("smtp.qq.com", 465) as server:
        server.login(QQ_EMAIL, QQ_SMTP_CODE)
        server.sendmail(QQ_EMAIL, [MAIL_TO], message.as_string())


# ---------------- 主流程 ----------------

def main() -> None:
    print("检索式：")
    print(build_expression())
    print()

    pushed = load_pushed()
    chosen: set[str] = set()

    pool = search_ncpssd()
    picked, used_days = pick_top_articles(
        pool,
        pushed,
        chosen,
        RESULT_COUNT,
    )

    if not picked:
        print("没有可推送的新文献。")
        return

    articles: list[dict[str, Any]] = []

    for article in picked:
        print(f"[选中] {article['title']}")
        chosen.add(article["title"])

        reason = get_reason(article)
        articles.append(
            {
                "article": article,
                "reason": reason,
            }
        )

    content_html = build_email_html(articles, used_days)
    today_text = datetime.now().strftime("%Y-%m-%d")
    subject = f"新闻传播学每日文献 {today_text}"

    OUTPUT_DIR.mkdir(exist_ok=True)
    output_file = OUTPUT_DIR / f"{today_text}.html"
    output_file.write_text(content_html, encoding="utf-8")
    print(f"[输出] 已生成：{output_file}")

    if DRY_RUN:
        print("\n=== DRY RUN：不发送邮件，不写入 pushed.txt ===\n")
        print(content_html)
        return

    send_email(subject, content_html)
    add_pushed([item["article"]["title"] for item in articles])
    print("邮件已发送 →", MAIL_TO)


if __name__ == "__main__":
    main()