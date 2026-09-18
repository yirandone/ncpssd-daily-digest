from __future__ import annotations

import html
import json
import re
from typing import Any
from urllib.parse import quote

import requests


BASE_URL = "https://ncpssd.org"
SEARCH_URL = f"{BASE_URL}/searchHandler/search"

TARGET_JOURNALS = (
    "国际新闻界",
    "新闻与传播研究",
    "现代传播",
    "新闻大学",
)

TARGET_TOPICS = (
    "算法审计",
    "多模态新闻",
    "AI说服",
)

SORT_BY_TIME = "synUpdateType|DESC,date|DESC,ik_subject|DESC,id|DESC"


def clean_text(value: Any) -> str:
    """Clean NCPSSD list-field text for terminal display."""
    if value is None:
        return ""

    text = html.unescape(str(value))
    text = re.sub(r"<[^>]*>", "", text)
    text = re.sub(r"\[[^\]]*\]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def build_query() -> str:
    topic_conditions = []

    for topic in TARGET_TOPICS:
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
        for journal in TARGET_JOURNALS
    ]

    return (
        f'({" OR ".join(topic_conditions)}) '
        f'AND ({" OR ".join(journal_conditions)}) '
        'AND TYPE="中文期刊文章"'
    )


def make_detail_url(row: dict[str, Any]) -> str:
    encrypted_url = clean_text(row.get("encryptedUrl"))

    if not encrypted_url:
        return ""

    return (
        f"{BASE_URL}/Literature/secure/articleinfo"
        f"?params={quote(encrypted_url, safe='')}"
    )


def main() -> None:
    query = build_query()

    payload = {
        "search": query,
        "pageNum": 1,
        "pageSize": 10,
        "sort": SORT_BY_TIME,
        "sType": "0",
        "ajaxKeys": ",".join(TARGET_TOPICS),
        "customShowCondition": "NCPSSD test search",
    }

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Referer": f"{BASE_URL}/",
        "X-Requested-With": "XMLHttpRequest",
    }

    print("Requesting NCPSSD...")
    print("Query:")
    print(query)
    print()

    response = requests.post(
        SEARCH_URL,
        data=payload,
        headers=headers,
        timeout=30,
    )

    print(f"HTTP status: {response.status_code}")
    response.raise_for_status()

    try:
        body = response.json()
    except ValueError:
        print("The response was not JSON. First 1000 characters:")
        print(response.text[:1000])
        raise

    with open("ncpssd_response.json", "w", encoding="utf-8") as file:
        json.dump(body, file, ensure_ascii=False, indent=2)

    data = body.get("data")

    if not isinstance(data, dict):
        print("Unexpected response:")
        print(json.dumps(body, ensure_ascii=False, indent=2)[:3000])
        return

    total = data.get("total", 0)
    rows = data.get("rows", [])

    print(f"Total records: {total}")
    print(f"Rows returned: {len(rows)}")
    print("Raw response saved to: ncpssd_response.json")
    print()

    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            continue

        print(f"{index}. {clean_text(row.get('ik_title') or row.get('title'))}")
        print(f"   Type: {clean_text(row.get('type'))}")
        print(f"   Authors: {clean_text(row.get('ik_creator') or row.get('creator'))}")
        print(f"   Journal: {clean_text(row.get('cbw_name'))}")
        print(f"   Year/issue: {clean_text(row.get('years'))} / {clean_text(row.get('num'))}")
        print(f"   Keywords: {clean_text(row.get('ik_subject'))}")
        print(f"   Abstract: {clean_text(row.get('remark'))[:250]}")
        print(f"   Detail URL: {make_detail_url(row)}")
        print()


if __name__ == "__main__":
    main()