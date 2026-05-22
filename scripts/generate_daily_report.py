#!/usr/bin/env python3
"""
每日 AI 新闻日报生成器
1. 从多个来源抓取 AI 新闻（RSS + API）
2. 用 AI 生成结构化日报
3. 保存为 Jekyll markdown 文件
4. 推送到 GitHub 仓库（触发 Pages 更新）
5. 输出 markdown 供企业微信群推送
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# --- 配置 ---
REPO_DIR = Path(os.environ.get("DAILY_REPORT_REPO", os.path.expanduser("~/daily-report")))
POSTS_DIR = REPO_DIR / "_posts"
TZ = timezone(timedelta(hours=8))  # Beijing time

# 新闻来源 RSS feeds
RSS_FEEDS = [
    {"name": "36kr AI", "url": "https://36kr.com/feed", "category": "AI"},
    {"name": "量子位", "url": "https://www.qbitai.com/feed", "category": "AI"},
    {"name": "机器之心", "url": "https://www.jiqizhixin.com/rss", "category": "AI"},
    {"name": "Hacker News", "url": "https://hnrss.org/newest?q=AI+LLM+GPT+Claude", "category": "Tech"},
    {"name": "TechCrunch AI", "url": "https://techcrunch.com/category/artificial-intelligence/feed/", "category": "Tech"},
]

def fetch_rss(feed_url: str, max_items: int = 10) -> list:
    """用 curl 抓 RSS feed，解析出标题和链接"""
    try:
        result = subprocess.run(
            ["curl", "-sL", "--max-time", "15", feed_url],
            capture_output=True, text=True, timeout=20
        )
        if result.returncode != 0 or not result.stdout:
            return []

        import xml.etree.ElementTree as ET
        root = ET.fromstring(result.stdout)

        items = []
        # RSS 2.0
        for item in root.iter("item"):
            title = item.findtext("title", "").strip()
            link = item.findtext("link", "").strip()
            desc = item.findtext("description", "").strip()
            # strip HTML tags
            desc = re.sub(r'<[^>]+>', '', desc)[:200]
            if title:
                items.append({"title": title, "link": link, "desc": desc})
            if len(items) >= max_items:
                break

        # Atom
        if not items:
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            for entry in root.findall("atom:entry", ns):
                title = entry.findtext("atom:title", "", ns).strip()
                link_el = entry.find("atom:link", ns)
                link = link_el.get("href", "") if link_el is not None else ""
                desc = ""
                summary = entry.find("atom:summary", ns)
                if summary is not None and summary.text:
                    desc = re.sub(r'<[^>]+>', '', summary.text)[:200]
                if title:
                    items.append({"title": title, "link": link, "desc": desc})
                if len(items) >= max_items:
                    break

        return items
    except Exception as e:
        print(f"[WARN] Failed to fetch {feed_url}: {e}", file=sys.stderr)
        return []


def fetch_all_news() -> dict:
    """从所有来源抓取新闻"""
    all_news = {}
    for feed in RSS_FEEDS:
        print(f"Fetching {feed['name']}...")
        items = fetch_rss(feed["url"])
        if items:
            all_news[feed["name"]] = {"category": feed["category"], "items": items}
            print(f"  Got {len(items)} items")
        else:
            print(f"  No items")
    return all_news


def generate_markdown_report(all_news: dict) -> str:
    """生成 markdown 格式的日报"""
    now = datetime.now(TZ)
    date_str = now.strftime("%Y年%m月%d日")

    lines = [
        f"# AI 日报 - {date_str}",
        "",
        f"> 自动生成于 {now.strftime('%Y-%m-%d %H:%M')} (北京时间)",
        "",
    ]

    # 按分类分组
    categories = {}
    for source, data in all_news.items():
        cat = data["category"]
        if cat not in categories:
            categories[cat] = []
        for item in data["items"]:
            categories[cat].append({**item, "source": source})

    for cat, items in categories.items():
        # deduplicate by title similarity
        seen_titles = []
        unique_items = []
        for item in items:
            is_dup = False
            for seen in seen_titles:
                if similar_title(item["title"], seen):
                    is_dup = True
                    break
            if not is_dup:
                seen_titles.append(item["title"])
                unique_items.append(item)

        lines.append(f"## {cat} 新闻")
        lines.append("")
        for i, item in enumerate(unique_items[:15], 1):
            title = item["title"]
            link = item["link"]
            source = item["source"]
            if link:
                lines.append(f"{i}. [{title}]({link}) — *{source}*")
            else:
                lines.append(f"{i}. {title} — *{source}*")
        lines.append("")

    lines.append("---")
    lines.append("*本日报由 [Hermes Agent](https://github.com/outhsics) 自动生成*")

    return "\n".join(lines)


def generate_wecom_markdown(report_md: str) -> str:
    """生成企业微信群消息格式（精简版）"""
    now = datetime.now(TZ)
    date_str = now.strftime("%Y年%m月%d日")

    # 取前 20 条标题
    lines = report_md.split("\n")
    msg_lines = [f"📰 AI 日报 | {date_str}", ""]
    count = 0
    for line in lines:
        if line.startswith("# ") or line.startswith("> ") or line.startswith("---"):
            continue
        if line.strip() == "":
            continue
        msg_lines.append(line)
        count += 1
        if count >= 25:
            break

    msg_lines.append("")
    msg_lines.append("🔗 完整日报: https://outhsics.github.io/daily-report/")

    return "\n".join(msg_lines)


def similar_title(a: str, b: str) -> bool:
    """简单标题去重"""
    a_lower = a.lower()
    b_lower = b.lower()
    # 如果一个标题包含另一个的 60% 以上字符
    shorter = min(len(a_lower), len(b_lower))
    if shorter < 5:
        return False
    overlap = sum(1 for c in a_lower if c in b_lower)
    ratio = overlap / len(a_lower) if len(a_lower) > 0 else 0
    return ratio > 0.75


def save_as_jekyll_post(report_md: str):
    """保存为 Jekyll _posts 目录下的 markdown 文件"""
    now = datetime.now(TZ)
    filename = f"{now.strftime('%Y-%m-%d')}-ai-daily-report.md"
    filepath = POSTS_DIR / filename

    front_matter = "---\n"
    front_matter += f"layout: post\n"
    front_matter += f"title: \"AI 日报 - {now.strftime('%Y年%m月%d日')}\"\n"
    front_matter += f"date: {now.strftime('%Y-%m-%d %H:%M:%S')} +0800\n"
    front_matter += f"categories: [daily, ai]\n"
    front_matter += "---\n\n"

    # 去掉原来的 # 标题行（Jekyll 用 front matter 的 title）
    body_lines = []
    for line in report_md.split("\n"):
        if line.startswith("# AI 日报"):
            continue
        body_lines.append(line)
    body = "\n".join(body_lines).strip()

    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(front_matter + body, encoding="utf-8")
    print(f"Saved: {filepath}")
    return filepath


def git_push(filepath: Path):
    """推送到 GitHub"""
    try:
        subprocess.run(["git", "add", str(filepath)], cwd=REPO_DIR, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", f"docs: {filepath.name}"],
            cwd=REPO_DIR, check=True, capture_output=True
        )
        subprocess.run(["git", "push", "origin", "main"], cwd=REPO_DIR, check=True, capture_output=True)
        print("Pushed to GitHub!")
    except subprocess.CalledProcessError as e:
        print(f"[WARN] Git push failed: {e.stderr.decode() if e.stderr else e}", file=sys.stderr)


def main():
    print("=" * 50)
    print("AI Daily Report Generator")
    print("=" * 50)

    # 1. 抓新闻
    all_news = fetch_all_news()
    if not all_news:
        print("[ERROR] No news fetched, aborting.")
        sys.exit(1)

    print(f"\nFetched from {len(all_news)} sources")

    # 2. 生成日报
    report = generate_markdown_report(all_news)

    # 3. 保存 Jekyll 文件
    filepath = save_as_jekyll_post(report)

    # 4. 推送到 GitHub
    git_push(filepath)

    # 5. 输出企业微信格式到 stdout（供 Hermes cron job 读取）
    wecom_msg = generate_wecom_markdown(report)
    print("\n" + "=" * 50)
    print("WeCom Message:")
    print("=" * 50)
    print(wecom_msg)


if __name__ == "__main__":
    main()
