# Jamf Protect Threat Prevention Changelog → RSS Feed

Automatically scrapes the [Jamf Protect Threat Prevention Changelog](https://learn.jamf.com/en-US/bundle/jamf-protect-threat-prevention-changelog/page/Jamf_Protect_Threat_Prevention_Changelog.html) daily and publishes an RSS feed via GitHub Pages.

## How it works

1. A GitHub Actions workflow runs daily at 08:00 UTC
2. It uses Playwright (headless Chromium) to render the JavaScript-heavy changelog page
3. BeautifulSoup parses the rendered HTML and extracts dated entries
4. An RSS 2.0 XML feed is generated and deployed to GitHub Pages

## Setup

RSS feed URL:

```
https://<your-username>.github.io/jamf-changelog-rss/feed.xml
```