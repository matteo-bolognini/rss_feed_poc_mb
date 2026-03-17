# Jamf Protect Threat Prevention Changelog → RSS Feed

Automatically scrapes the [Jamf Protect Threat Prevention Changelog](https://learn.jamf.com/en-US/bundle/jamf-protect-threat-prevention-changelog/page/Jamf_Protect_Threat_Prevention_Changelog.html) daily and publishes an RSS feed via GitHub Pages.

## How it works

1. A GitHub Actions workflow runs daily at 08:00 UTC
2. It uses Playwright (headless Chromium) to render the JavaScript-heavy changelog page
3. BeautifulSoup parses the rendered HTML and extracts dated entries
4. An RSS 2.0 XML feed is generated and deployed to GitHub Pages

## Setup

### 1. Create the repo

```bash
git clone <this-repo>
cd jamf-changelog-rss
git init   # if not already a git repo
git add .
git commit -m "Initial commit"
```

### 2. Push to GitHub

```bash
gh repo create jamf-changelog-rss --public --push
# or create manually on github.com and push
```

### 3. Enable GitHub Pages

1. Go to your repo → **Settings** → **Pages**
2. Under **Source**, select **GitHub Actions**
3. That's it — no need to pick a branch

### 4. Run it

The workflow runs automatically every day, but you can trigger it immediately:

```bash
gh workflow run "Update Jamf Changelog RSS Feed"
```

Or go to **Actions** → **Update Jamf Changelog RSS Feed** → **Run workflow**

### 5. Subscribe

Once deployed, your RSS feed URL will be:

```
https://<your-username>.github.io/jamf-changelog-rss/feed.xml
```

Add that URL to your RSS reader (NetNewsWire, Feedly, Inoreader, etc.).

## Customisation

- **Schedule**: Edit the `cron` value in `.github/workflows/update-feed.yml`
  - `"0 8 * * *"` = daily at 08:00 UTC
  - `"0 */6 * * *"` = every 6 hours
  - `"0 8 * * 1-5"` = weekdays only at 08:00 UTC
- **Entry count**: Change `entries[:50]` in `scrape.py` to keep more/fewer items

## Troubleshooting

If the feed is empty, the page structure may have changed. Check the Actions log for
the "WARNING: No entries found" message. You may need to update the parsing logic in
`extract_entries()` in `scrape.py`.

## Local testing

```bash
pip install -r requirements.txt
playwright install chromium
python scrape.py
# Check public/feed.xml
```

## Cost

Completely free. GitHub Actions provides 2,000 minutes/month for free on public repos,
and each run takes ~1-2 minutes. GitHub Pages hosting is also free.
