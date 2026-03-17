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
DEBUG_DIR = Path("debug")
DEBUG_HTML = DEBUG_DIR / "page.html"
DEBUG_TEXT = DEBUG_DIR / "page.txt"

# Common date patterns found in Jamf changelogs
DATE_PATTERNS = [
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}",
    r"\d{4}-\d{2}-\d{2}",
    r"\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}",
]

COMBINED_DATE_RE = re.compile("|".join(f"({p})" for p in DATE_PATTERNS))


def parse_date(text: str) -> datetime | None:
    """Try to parse a date string into a datetime object."""
    formats = [
        "%B %d, %Y",
        "%B %d %Y",
        "%Y-%m-%d",
        "%d %B %Y",
    ]
    cleaned = text.strip()
    cleaned = re.sub(r"\s+", " ", cleaned)

    # Try as-is first
    for fmt in formats:
        try:
            return datetime.strptime(cleaned, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    # Try without commas
    no_comma = cleaned.replace(",", "")
    no_comma = re.sub(r"\s+", " ", no_comma).strip()
    for fmt in formats:
        try:
            return datetime.strptime(no_comma, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    return None


def fetch_page() -> str:
    """Use Playwright to render the JS-heavy page and return its HTML."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        )
        page = context.new_page()

        print(f"Navigating to {CHANGELOG_URL}...")
        page.goto(CHANGELOG_URL, wait_until="networkidle", timeout=90000)

        # Wait for content to render — try multiple selectors
        selectors_to_try = [
            "table", "[class*='changelog']", "[class*='content']",
            "article", "main", ".topic-content", "[role='main']", "h2", "h3",
        ]
        for sel in selectors_to_try:
            try:
                page.wait_for_selector(sel, timeout=5000)
                print(f"  Found selector: {sel}")
                break
            except Exception:
                pass

        # Extra wait for dynamic content
        page.wait_for_timeout(8000)

        # Scroll to trigger lazy loading
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(3000)
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(2000)

        html = page.content()
        browser.close()
    return html


def extract_entries(html: str) -> list[dict]:
    """Parse the rendered HTML and extract changelog entries."""
    soup = BeautifulSoup(html, "html.parser")

    # Save debug info
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    DEBUG_HTML.write_text(html, encoding="utf-8")
    print(f"Debug HTML saved to {DEBUG_HTML} ({len(html)} bytes)")

    full_text = soup.get_text(separator="\n", strip=True)
    DEBUG_TEXT.write_text(full_text, encoding="utf-8")
    print(f"Debug text saved to {DEBUG_TEXT} ({len(full_text)} chars)")

    # Print debug info about page structure
    print(f"\nPage structure debug:")
    for tag in ["table", "h1", "h2", "h3", "h4", "tr", "article", "section"]:
        print(f"  <{tag}>: {len(soup.find_all(tag))}")

    body = soup.body
    if body:
        for child in body.children:
            if hasattr(child, 'get') and child.get('class'):
                print(f"  body > {child.name}.{'.'.join(child['class'])}")

    print(f"\nFirst 3000 chars of page text:")
    print(full_text[:3000])
    print("--- end preview ---\n")

    entries = []

    # Remove clutter
    for tag in soup.select("nav, header, footer, [role='navigation'], .sidebar, .toc"):
        tag.decompose()

    # Find main content area
    main_selectors = [
        "main", "[role='main']", ".content-body", ".topic-content",
        ".zn-body", "[class*='topic']", "article", "#content",
    ]
    main = None
    for sel in main_selectors:
        main = soup.select_one(sel)
        if main:
            print(f"Using main content from selector: {sel}")
            break
    if not main:
        main = soup.body or soup
        print("Falling back to full body")

    # ── Strategy 1: Table-based changelog ──
    tables = main.find_all("table")
    print(f"\nStrategy 1: Checking {len(tables)} tables...")
    for table in tables:
        rows = table.find_all("tr")
        for row in rows:
            cells = row.find_all(["td", "th"])
            row_text = row.get_text(strip=True)
            match = COMBINED_DATE_RE.search(row_text)
            if match and cells:
                date = parse_date(match.group(0))
                if not date:
                    continue
                parts = []
                for cell in cells:
                    cell_text = cell.get_text(separator=" ", strip=True)
                    if match.group(0) not in cell_text:
                        parts.append(cell_text)
                    elif cell_text != match.group(0):
                        remaining = cell_text.replace(match.group(0), "").strip()
                        if remaining:
                            parts.append(remaining)
                body = " | ".join(p for p in parts if p) or row_text
                entries.append({
                    "title": f"Changelog Update — {match.group(0)}",
                    "date": date,
                    "body": body,
                })
    if entries:
        print(f"  Found {len(entries)} entries from tables")

    # ── Strategy 2: Heading-based entries ──
    if not entries:
        print("Strategy 2: Checking headings...")
        headings = main.find_all(re.compile(r"^h[1-6]$", re.I))
        for heading in headings:
            text = heading.get_text(strip=True)
            match = COMBINED_DATE_RE.search(text)
            if match:
                date = parse_date(match.group(0))
                if not date:
                    continue
                content_parts = []
                sibling = heading.find_next_sibling()
                while sibling:
                    if sibling.name and re.match(r"^h[1-6]$", sibling.name, re.I):
                        break
                    content_parts.append(sibling.get_text(separator=" ", strip=True))
                    sibling = sibling.find_next_sibling()
                body = "\n".join(p for p in content_parts if p)
                if body:
                    entries.append({"title": text, "date": date, "body": body})
        if entries:
            print(f"  Found {len(entries)} entries from headings")

    # ── Strategy 3: Bold/strong date markers ──
    if not entries:
        print("Strategy 3: Checking bold/strong markers...")
        markers = main.find_all(["strong", "b", "dt", "th", "td", "span", "p", "div", "li"])
        seen_dates = set()
        for marker in markers:
            text = marker.get_text(strip=True)
            if len(text) > 200:
                continue
            match = COMBINED_DATE_RE.search(text)
            if not match:
                continue
            date = parse_date(match.group(0))
            if not date or date in seen_dates:
                continue
            seen_dates.add(date)

            container = marker.find_parent(["div", "section", "tr", "article", "li", "dd"])
            if container:
                body = container.get_text(separator=" ", strip=True)
            else:
                parts = []
                sib = marker.find_next_sibling()
                count = 0
                while sib and count < 20:
                    parts.append(sib.get_text(separator=" ", strip=True))
                    sib = sib.find_next_sibling()
                    count += 1
                body = "\n".join(p for p in parts if p) or text
            entries.append({
                "title": f"Changelog Update — {match.group(0)}",
                "date": date,
                "body": body,
            })
        if entries:
            print(f"  Found {len(entries)} entries from markers")

    # ── Strategy 4: Raw text line scanning ──
    if not entries:
        print("Strategy 4: Scanning raw text lines...")
        lines = full_text.split("\n")
        current_entry = None
        for line in lines:
            line = line.strip()
            if not line:
                continue
            match = COMBINED_DATE_RE.search(line)
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
                    remainder = line.replace(match.group(0), "").strip(" -–—:|")
                    if remainder:
                        current_entry["body"] = remainder + "\n"
                    continue
            if current_entry is not None:
                current_entry["body"] += line + "\n"
        if current_entry and current_entry["body"]:
            entries.append(current_entry)
        if entries:
            print(f"  Found {len(entries)} entries from text scanning")

    # Deduplicate and sort newest first
    seen = set()
    unique = []
    for e in entries:
        key = (e["date"].isoformat(), e["body"][:100])
        if key not in seen:
            seen.add(key)
            unique.append(e)
    unique.sort(key=lambda x: x["date"], reverse=True)

    print(f"\nTotal unique entries: {len(unique)}")
    for e in unique[:5]:
        print(f"  {e['date'].strftime('%Y-%m-%d')} | {e['title'][:60]} | {e['body'][:80]}...")

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

    for entry in entries[:50]:
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = entry["title"]
        desc = entry["body"].strip()[:500]
        if len(entry["body"]) > 500:
            desc += "…"
        ET.SubElement(item, "description").text = desc
        ET.SubElement(item, "link").text = CHANGELOG_URL
        ET.SubElement(item, "pubDate").text = entry["date"].strftime(
            "%a, %d %b %Y %H:%M:%S +0000"
        )
        guid_source = f"{entry['date'].isoformat()}-{entry['title']}"
        guid_hash = hashlib.sha256(guid_source.encode()).hexdigest()[:16]
        guid = ET.SubElement(item, "guid", isPermaLink="false")
        guid.text = f"jamf-changelog-{guid_hash}"

    ET.indent(rss, space="  ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(
        rss, encoding="unicode"
    )


def main():
    print("=" * 60)
    print("Jamf Protect Changelog RSS Scraper")
    print("=" * 60)

    print("\nFetching changelog page...")
    html = fetch_page()
    print(f"Got {len(html)} bytes of HTML")

    print("\nExtracting entries...")
    entries = extract_entries(html)
    print(f"\nFound {len(entries)} changelog entries")

    if not entries:
        print("WARNING: No entries found. The page structure may have changed.")
        print("Check the debug files in the 'debug' directory.")
        print("Generating empty feed...")

    print("\nBuilding RSS feed...")
    rss_xml = build_rss(entries)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(rss_xml, encoding="utf-8")
    print(f"RSS feed written to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
