# African Capital Source — independent news collection

This update keeps the existing newspaper layout, fonts, navigation, article templates,
advertising positions, search and responsive CSS. It replaces the reader's Claude
database dependency with public news data, collected by a scheduled Python job.
There are no AI calls, API keys, npm packages or database subscription requirements.

## What is included

- The existing index.html, modified to load public JSON and identify source stories.
- 24 initial publisher configurations selected from the supplied catalogue.
- The full 683-entry catalogue in config/source-catalog.csv.
- RSS and Atom discovery, metadata collection, topic/country matching and URL deduplication.
- A GitHub Actions job scheduled at minutes 7 and 37 of each hour (UTC).
- A separate acs-data branch containing the collected data.
- Public, read-only collection health at source-status.html and in each Actions run summary.
- An importer for the existing Claude article/rate exports.
- Automated tests for ingestion, failures, filtering, data validation and JavaScript syntax.

This is an overlay for the existing repository, not a complete copy of its photo library.
Keep the existing img/ and ph/ folders. No sample or invented news is shipped.

## Before the first deployment

1. Add these files to a working branch of lwaziagain/Africa-Capital-Resource, preserving
   their paths. Replace index.html; keep all existing images. Include .github/workflows/
   and .gitignore, which may be hidden in a file browser.
2. Review the changes, run the checks below and merge to the default branch.
3. Open GitHub → Actions → Collect news → Run workflow, on the default branch.
4. Check the run summary. A responding feed is a technical check, not a reuse licence.
   Disable failing or unsuitable sources in config/sources.json. Each source begins
   with headlines/links only; excerpts are disabled.
5. Confirm that the acs-data branch was created and contains data/articles.json and
   data/status.json. No news will appear until at least one usable feed responds.
6. Deploy the updated default branch through the existing hosting project. If the
   project already deploys GitHub main automatically, merging normally starts that
   deployment. Keep the existing domain and DNS configuration.
7. Open the homepage, a category, a story and source-status.html on the real domain.
   Verify that raw.githubusercontent.com is permitted by any hosting CSP/connect-src.

The workflow needs repository Contents write permission to create/update acs-data.
The job declares that permission; repository/organisation policies can still prohibit
it. An owner may need to allow the workflow or provide an approved alternative.
No personal access token is included or required by the normal workflow.

## How the reader gets updates

The website fetches the public data branch directly, avoiding a website redeploy for
every collection. It also merges a local editorial/archive file from data/articles.json.
If the remote request fails, the local archive is used and the page reports that it is
showing saved content. If no local archive exists, an unavailable/preparing state appears.

Configuration lives in assets/site-config.js. Update the owner/repository URLs if the
project is moved or forked. This version assumes the repository and collected metadata
remain public. It is not suitable for private drafts, messages or subscriber records.

GitHub's scheduler is best-effort. A 30-minute schedule is not an instant publication
guarantee. Public raw-file caching adds some delay. Readers get current data on page
load and when returning to a tab after five minutes. A production service with strict
freshness requirements should eventually use a dedicated scheduler and a database/API.

## What gets published

New entries are labelled Source story. They retain the publisher's headline, URL and
publication time when supplied, plus the time ACS collected the entry. Readers follow
the original link for the full report. ACS does not claim to have written or independently
verified these entries.

By default, collection does not copy full article bodies, images or excerpts. Existing
local illustrative photos are retained. Excerpts can be enabled per source only after
the publisher's reuse terms have been reviewed; they are limited to 240 characters.
RSS access and robots.txt availability do not themselves grant republication rights.

No AI analysis is generated. The original full ACS article layout remains available
for imported or manually written reports. Empty analysis fields are not invented.
Country matching uses explicit names in feed metadata and falls back to Pan-African;
topic matching is rule-based and can be wrong. Entries without a publication timestamp
are labelled accordingly, rather than assigning a made-up event date.

## Managing sources

Edit config/sources.json. Each entry has:

- id: unique stable identifier.
- name and website: publisher name and homepage.
- feed: a known RSS/Atom URL, or null to discover the homepage's alternate-feed link.
  When there is no advertised feed, one conventional /feed/ endpoint is tried.
- enabled: false pauses that source.
- category: fallback ACS section; fixed_category keeps it instead of keyword matching.
- allow_excerpt: false by default.
- include_keywords: optional relevance filter; at least one keyword must match.

The remaining catalogue is a research backlog, not 659 additional working connections.
Add sources gradually. General-interest feeds benefit from a business-specific feed
or include_keywords. Add an exact feed URL when discovery finds the wrong feed.
The collector does not bypass paywalls, access blocks, login requirements or robots rules.

The 24 initial configurations have not yet been live-verified from this build environment:
outbound DNS was unavailable. Their first GitHub run will discover feeds and report which
respond. There is no promise that all 24, or all 683 catalogue entries, can be collected.

## Errors, duplicates and retention

- A failing source does not stop successful sources.
- A complete source failure preserves the archive and marks the job failed.
- Malformed archive JSON stops collection rather than overwriting it with an empty list.
- Feed requests use ETag/Last-Modified where available and have size/time limits.
- URLs are normalised to remove common tracking parameters. Repeated URLs are skipped.
  Similar reporting from different publishers is not merged automatically.
- Existing entries are not silently rewritten when a publisher changes its headline.
  The original link is authoritative for later corrections.
- The first import accepts stories from the previous 30 days. Future-dated entries beyond
  a one-day clock allowance are skipped. The newest 3,000 collected entries are retained.
  Imported/manual reports are not pruned by that limit.
- Add an unwanted article's canonical URL to data/suppressed-urls.json on the default
  branch to remove it on the next collection and prevent it from returning.
  This is removal from the site, not erasure from public Git history.

Public scheduled workflows can be disabled by GitHub after repository inactivity.
Monitor Actions and source-status.html; re-enable the workflow if necessary. Source
feeds and schemas can change, so this is unattended operation, not zero maintenance.

## Recovering the existing archive

Ask Claude to export articles and rates as JSON, preserving all fields and IDs.
Do not export messages, subscriber information or contact enquiries into this repository.
Save the exports outside the repository, then run:

    python3 scripts/import_archive.py --articles /path/to/articles.json --rates /path/to/rates.json

Only records with status "published" are imported. Review data/articles.json and
data/rates.json before committing. The reader combines that archive with new feed entries.
Plain arrays, objects with articles/rates arrays, and records shaped as {id, data} are
supported. Other export formats need conversion.

## Market data and forms

News collection does not generate exchange rates, policy rates or market prices.
Existing rate exports can still render; no live financial feed is included.

Contact, advertising-enquiry and newsletter forms previously wrote to Claude. They are
now visibly unavailable and disabled, rather than accepting details without delivery.
Connecting a form/email provider is a separate task. None of these personal records should
be placed in public JSON. Advertising layout and company ownership wording are preserved.

## Run the checks

From the repository root:

    python3 -m unittest discover -s tests -p 'test_*.py' -v
    node --test tests/news-data.test.cjs

To collect manually on a machine with internet access:

    python3 scripts/collect.py --output data

For local browsing, serve the directory over HTTP rather than opening index.html as a file:

    python3 -m http.server 8000

Use local data URLs in assets/site-config.js for an entirely local preview.

## Costs and limitations

There is no AI charge and no database account needed for this implementation.
Standard GitHub-hosted Actions runners are free for public repositories under the current
GitHub terms. Existing hosting/domain charges continue. Paid feeds, future private
repositories, higher service limits or optional editorial tools can add costs.
This implementation makes no purchase and enables no paid third-party service.

The public JSON approach is a practical first release. As volume, search traffic and
editorial requirements grow, keep the same front end and move collected data to a
database/API with pagination and a stronger uptime/freshness target.

## References

- https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows
- https://docs.github.com/en/actions/concepts/billing-and-usage
- https://developer.wordpress.org/advanced-administration/wordpress/feeds/

## Build verification

Base repository commit: 76b007a9cc87c7a06616ff10ed189ae4fe99c070.
All 27 automated ingestion/data-adapter/template tests passed. Workflow YAML and shell syntax passed, and two publishing cycles were verified against a temporary Git repository without changing its website branch.
The existing CSS blocks were preserved. Browser visual verification was blocked by the
local preview restrictions; live feeds, GitHub execution and deployment must be verified
after authenticated repository access is restored. No production deployment is claimed.
