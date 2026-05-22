#!/usr/bin/env python3
"""
每日 AI 新闻日报生成器
1. 从多个来源抓取 AI 新闻（RSS + API）
2. 生成结构化日报数据（JSON）
3. 渲染到静态 HTML（GitHub Pages）
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
DATA_DIR = REPO_DIR / "data"
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


def similar_title(a: str, b: str) -> bool:
    """简单标题去重"""
    a_lower = a.lower()
    b_lower = b.lower()
    shorter = min(len(a_lower), len(b_lower))
    if shorter < 5:
        return False
    overlap = sum(1 for c in a_lower if c in b_lower)
    ratio = overlap / len(a_lower) if len(a_lower) > 0 else 0
    return ratio > 0.75


def build_report_data(all_news: dict) -> list:
    """构建结构化报告数据（用于 JSON + HTML）"""
    now = datetime.now(TZ)
    date_str = now.strftime("%Y年%m月%d日")
    time_str = now.strftime("%Y-%m-%d %H:%M")

    # 按分类分组并去重
    categories = {}
    for source, data in all_news.items():
        cat = data["category"]
        if cat not in categories:
            categories[cat] = []
        for item in data["items"]:
            categories[cat].append({**item, "source": source})

    sections = []
    for cat, items in categories.items():
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

        sections.append({
            "name": f"{cat} 新闻",
            "items": [
                {"title": it["title"], "link": it["link"], "source": it["source"]}
                for it in unique_items[:15]
            ]
        })

    return [{
        "title": f"AI 日报",
        "date": f"{date_str} {time_str}",
        "sections": sections,
    }]


def generate_markdown_report(report_data: list) -> str:
    """从结构化数据生成 markdown 格式日报"""
    report = report_data[0]
    lines = [
        f"# AI 日报 - {report['date']}",
        "",
    ]
    for section in report["sections"]:
        lines.append(f"## {section['name']}")
        lines.append("")
        for i, item in enumerate(section["items"], 1):
            if item["link"]:
                lines.append(f"{i}. [{item['title']}]({item['link']}) — *{item['source']}*")
            else:
                lines.append(f"{i}. {item['title']} — *{item['source']}*")
        lines.append("")

    lines.append("---")
    lines.append("*本日报由 [Hermes Agent](https://github.com/outhsics) 自动生成*")
    return "\n".join(lines)


def generate_wecom_markdown(report_data: list) -> str:
    """生成企业微信群消息格式（精简版）"""
    report = report_data[0]
    now = datetime.now(TZ)
    date_str = now.strftime("%Y年%m月%d日")

    msg_lines = [f"AI 日报 | {date_str}", ""]
    count = 0
    for section in report["sections"]:
        msg_lines.append(f"【{section['name']}】")
        for i, item in enumerate(section["items"][:8], 1):
            msg_lines.append(f"{i}. {item['title']} — {item['source']}")
            count += 1
            if count >= 20:
                break
        msg_lines.append("")
        if count >= 20:
            break

    msg_lines.append("完整日报: https://outhsics.github.io/daily-report/")
    return "\n".join(msg_lines)


def save_data_json(report_data: list, all_reports: list):
    """保存 JSON 数据文件"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    data_file = DATA_DIR / "reports.json"
    data_file.write_text(json.dumps(all_reports, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved data: {data_file}")
    return data_file


def render_html(report_data: list):
    """将数据注入 index.html 并生成最终页面"""
    html_template = REPO_DIR / "index.html"
    if not html_template.exists():
        print("[WARN] index.html not found, skipping HTML render", file=sys.stderr)
        return None

    template = html_template.read_text(encoding="utf-8")
    # 注入 JSON 数据替换占位符
    json_str = json.dumps(report_data, ensure_ascii=False)
    html = template.replace("REPORT_DATA_PLACEHOLDER", json_str)

    html_file = REPO_DIR / "index.html"
    html_file.write_text(html, encoding="utf-8")
    print(f"Rendered: {html_file}")
    return html_file


def load_existing_reports() -> list:
    """加载已有的报告数据"""
    data_file = DATA_DIR / "reports.json"
    if data_file.exists():
        try:
            return json.loads(data_file.read_text(encoding="utf-8"))
        except:
            return []
    return []


def git_push(files: list):
    """推送到 GitHub"""
    try:
        for f in files:
            subprocess.run(["git", "add", str(f)], cwd=REPO_DIR, check=True, capture_output=True)
        now = datetime.now(TZ)
        subprocess.run(
            ["git", "commit", "-m", f"docs: AI日报 {now.strftime('%Y-%m-%d')}"],
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

    # 2. 构建结构化数据
    report_data = build_report_data(all_news)

    # 3. 加载已有报告，追加新报告（保留最近 30 天）
    all_reports = load_existing_reports()
    all_reports = report_data + all_reports[:30]

    # 4. 保存 JSON 数据
    data_file = save_data_json(report_data, all_reports)

    # 5. 渲染 HTML（用今天的报告数据）
    html_file = render_html(report_data)

    # 6. 推送到 GitHub
    files_to_push = [str(data_file)]
    if html_file:
        files_to_push.append(str(html_file))
    git_push(files_to_push)

    # 7. 输出企业微信格式到 stdout
    wecom_msg = generate_wecom_markdown(report_data)
    print("\n" + "=" * 50)
    print("WeCom Message:")
    print("=" * 50)
    print(wecom_msg)


if __name__ == "__main__":
    main()
