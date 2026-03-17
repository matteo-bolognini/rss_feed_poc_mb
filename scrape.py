#!/usr/bin/env python3
"""
Scrape the Jamf Protect Threat Prevention Changelog and generate an RSS feed.

The changelog page is JavaScript-rendered (Zoomin Software), so we use
Playwright to get the fully rendered HTML, then parse out dated entries
and produce a valid RSS 2.0 XML file.
"""

import re
import hashlib
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

CHANGELOG_URL = (
    "https://learn.jamf.com/en-US/bundle/jamf-protect-threat-prevention-changelog"
    "/page/Jamf_Protect_Threat_Prevention_Changelog.html"
)
OUTPUT_DIR = Path("public")
OUTPUT_FILE = OUTPUT_DIR / "feed.xml"

# Common date patterns found in Jamf changelogs, e.g. "March 14, 2026" or "2026-03-14"
DATE_PATTERNS = [
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}",
    r"\d{4}-\d{2}-\d{2}",
    r"\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}",
]


def parse_date(text: str) -> datetime | None:
    """Try to parse a date string into a datetime object."""
    formats = [
        "%B %d, %Y",
        "%B %d %Y",
        "%Y-%m-%d",
        "%d %B %Y",
    ]
    cleaned = text.strip().replace(",", ", ").replace("  ", " ").strip()
    # Normalise comma placement: "March 14 2026" vs "March 14, 2026"
    for fmt in formats:
        try:
            return datetime.strptime(cleaned, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def fetch_page() -> str:
    """Use Playwright to render the JS-heavy page and return its HTML."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        )
        page = context.new_page()
        page.goto(CHANGELOG_URL, wait_until="networkidle", timeout=60000)
        # Give extra time for dynamic content to settle
        page.wait_for_timeout(5000)
        html = page.content()
        browser.close()
    return html


def extract_entries(html: str) -> list[dict]:
    """
    Parse the rendered HTML and extract changelog entries.

    Strategy: look for date-like headings/text nodes that introduce each
    changelog section, then capture the content that follows until the
    next date heading.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Remove nav, header, footer, sidebar clutter
    for tag in soup.select("nav, header, footer, [role='navigation'], .sidebar"):
        tag.decompose()

    # Try to find the main content area
    main = soup.select_one("main, [role='main'], .content-body, .topic-content, article")
    if not main:
        main = soup.body or soup

    entries = []
    combined_pattern = "|".join(f"({p})" for p in DATE_PATTERNS)

    # Strategy 1: Look for headings (h1-h4) containing dates
    headings = main.find_all(re.compile(r"^h[1-4]$", re.I))
    for heading in headings:
        text = heading.get_text(strip=True)
        match = re.search(combined_pattern, text)
        if match:
            date = parse_date(match.group(0))
            if not date:
                continue

            # Collect all sibling content until the next heading of same or higher level
            content_parts = []
            sibling = heading.find_next_sibling()
            while sibling:
                if sibling.name and re.match(r"^h[1-4]$", sibling.name, re.I):
                    break
                content_parts.append(sibling.get_text(separator=" ", strip=True))
                sibling = sibling.find_next_sibling()

            body = "\n".join(p for p in content_parts if p)
            if body:
                entries.append({
                    "title": text,
                    "date": date,
                    "body": body,
                })

    # Strategy 2: If no heading-based entries found, look for date patterns
    # in any prominent text (bold, strong, dt, th, etc.)
    if not entries:
        markers = main.find_all(["strong", "b", "dt", "th", "td", "p", "div", "span"])
        seen_dates = set()
        for marker in markers:
            text = marker.get_text(strip=True)
            match = re.search(combined_pattern, text)
            if not match:
                continue
            date = parse_date(match.group(0))
            if not date or date in seen_dates:
                continue
            seen_dates.add(date)

            # Grab the parent block and its text
            parent = marker.find_parent(["div", "section", "tr", "article", "li"])
            if parent:
                body = parent.get_text(separator=" ", strip=True)
            else:
                body = text

            entries.append({
                "title": f"Changelog Update — {match.group(0)}",
                "date": date,
                "body": body,
            })

    # Strategy 3: Fall back to scanning all text for date patterns
    if not entries:
        full_text = main.get_text(separator="\n")
        lines = full_text.split("\n")
        current_entry = None
        for line in lines:
            line = line.strip()
            if not line:
                continue
            match = re.search(combined_pattern, line)
            if match:
                date = parse_date(match.group(0))
                if date:
                    if current_entry and current_entry["body"]:
                        entries.append(current_entry)
                    current_entry = {
                        "title": f"Changelog Update — {match.group(0)}",
                        "date": date,
                        "body": "",
                    }
                    continue
            if current_entry is not None:
                current_entry["body"] += line + "\n"

        if current_entry and current_entry["body"]:
            entries.append(current_entry)

    # Deduplicate and sort newest first
    seen = set()
    unique = []
    for e in entries:
        key = (e["date"].isoformat(), e["title"])
        if key not in seen:
            seen.add(key)
            unique.append(e)
    unique.sort(key=lambda x: x["date"], reverse=True)

    return unique


def build_rss(entries: list[dict]) -> str:
    """Build an RSS 2.0 XML string from the parsed entries."""
    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")

    ET.SubElement(channel, "title").text = "Jamf Protect Threat Prevention Changelog"
    ET.SubElement(channel, "link").text = CHANGELOG_URL
    ET.SubElement(channel, "description").text = (
        "Unofficial RSS feed for the Jamf Protect Threat Prevention Changelog. "
        "Auto-generated by scraping the official Jamf Learning Hub page."
    )
    ET.SubElement(channel, "language").text = "en-us"
    ET.SubElement(channel, "lastBuildDate").text = (
        datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    )

    for entry in entries[:50]:  # Keep last 50 entries
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = entry["title"]

        # Truncate body for description, full text in content
        desc = entry["body"][:500]
        if len(entry["body"]) > 500:
            desc += "…"
        ET.SubElement(item, "description").text = desc

        ET.SubElement(item, "link").text = CHANGELOG_URL
        ET.SubElement(item, "pubDate").text = entry["date"].strftime(
            "%a, %d %b %Y %H:%M:%S +0000"
        )

        # Generate a stable GUID from date + title
        guid_source = f"{entry['date'].isoformat()}-{entry['title']}"
        guid_hash = hashlib.sha256(guid_source.encode()).hexdigest()[:16]
        guid = ET.SubElement(item, "guid", isPermaLink="false")
        guid.text = f"jamf-changelog-{guid_hash}"

    ET.indent(rss, space="  ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(
        rss, encoding="unicode"
    )


def main():
    print("Fetching changelog page...")
    html = fetch_page()
    print(f"Got {len(html)} bytes of HTML")

    print("Extracting entries...")
    entries = extract_entries(html)
    print(f"Found {len(entries)} changelog entries")

    if not entries:
        print("WARNING: No entries found. The page structure may have changed.")
        print("Generating empty feed...")

    print("Building RSS feed...")
    rss_xml = build_rss(entries)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(rss_xml, encoding="utf-8")
    print(f"RSS feed written to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
