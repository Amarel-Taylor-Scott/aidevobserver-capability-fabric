# RapidAPI Facebook Ingest

This module turns Facebook page/profile post scrapes into candidate-only
normalized social post records.

Boundary:

```text
candidate_intake = true
serves_truth = false
```

The scraper does not promote posts, extracted claims, primitive drafts, or
source matches into truth. Licensing review, proof fixtures, PlanLocks, and
promotion must happen later.

## Inputs

Default source list:

```bash
aidevobserver-fabric social-sources --compact
```

Example source file:

```text
examples/facebook_sources.json
```

Provider config template:

```text
examples/rapidapi_facebook_provider.example.json
```

Discovered working provider config:

```text
examples/rapidapi_facebook_scraper3_provider.example.json
```

This provider uses a two-step flow:

```text
page/profile URL -> page_id/profile_id -> page/profile posts
```

When `--include-comments` is passed, the working provider also fetches:

```text
post_id -> /post/comments -> normalized comments + links + github_repo_urls
```

RapidAPI providers differ in endpoint paths, query parameter names, and response
shapes. Store those details in the provider JSON instead of hard-coding them in
Python.

The runtime supports two provider modes:

- `url_posts`: one request from source URL to post records;
- `facebook_scraper3_auto`: resolve a page/profile ID first, then fetch posts.

## Provider Selection

In RapidAPI, search for a Facebook page or Facebook post scraping API. For the
selected API, copy these fields into a provider JSON file:

- `host`: the RapidAPI host, usually ending in `.p.rapidapi.com`;
- `base_url`: usually `https://<host>`;
- `path`: the endpoint path for page/profile posts;
- `url_param`: the query parameter that accepts a Facebook page/profile URL;
- `limit_param`: optional query parameter for record count;
- `records_path`: optional dotted path to the list of post records in the JSON
  response.

Keep the key out of the provider JSON. The runtime reads it from an environment
variable, defaulting to `RAPIDAPI_KEY`.

## Dry Run

Print redacted request plans before making any external calls:

```bash
aidevobserver-fabric rapidapi-plan \
  --provider-config examples/rapidapi_facebook_provider.example.json \
  --sources examples/facebook_sources.json \
  --limit 10
```

The plan output includes `X-RapidAPI-Key: <redacted>`.

## Validate Provider And Key Readiness

Validate the selected provider config:

```bash
aidevobserver-fabric rapidapi-validate \
  --provider-config local/facebook_provider.json
```

Check whether the configured key environment variable is present without
printing the key:

```bash
aidevobserver-fabric rapidapi-key-status \
  --provider-config local/facebook_provider.json
```

The key-status command reports `present`, `length`, and `value:
<redacted>`. It never prints the key.

## Fixture Normalization

Before spending API calls, save one sample provider response as JSON and test
the response shape:

```bash
aidevobserver-fabric rapidapi-normalize-fixture \
  --provider-config local/facebook_provider.json \
  --sources examples/facebook_sources.json \
  --source-index 0 \
  --fixture examples/facebook_posts_fixture.json
```

If the fixture yields `record_count: 0`, update `records_path` in the provider
config to the dotted path containing the posts list.

## Live Smoke Test

Run one low-volume live request without printing raw post text:

```bash
export RAPIDAPI_KEY="..."

aidevobserver-fabric rapidapi-live-test \
  --provider-config examples/rapidapi_facebook_scraper3_provider.example.json \
  --sources examples/facebook_sources.json \
  --source-index 0 \
  --limit 1 \
  --include-comments
```

The live test returns record count and shape checks only.

## Scrape

After creating a real provider JSON:

```bash
export RAPIDAPI_KEY="..."

aidevobserver-fabric rapidapi-scrape \
  --provider-config examples/rapidapi_facebook_scraper3_provider.example.json \
  --sources examples/facebook_sources.json \
  --limit 10 \
  --include-comments \
  --out generated/facebook_posts.normalized.json
```

To test one source first:

```bash
aidevobserver-fabric rapidapi-scrape \
  --provider-config examples/rapidapi_facebook_scraper3_provider.example.json \
  --sources examples/facebook_sources.json \
  --source-index 0 \
  --limit 5 \
  --include-comments \
  --out generated/facebook_posts.deeprepo.normalized.json
```

The output shape is:

```json
{
  "candidate_only": true,
  "provider": {},
  "record_count": 0,
  "records": [],
  "serves_truth": false
}
```

Each normalized post includes:

- `source_id`;
- `source_url`;
- `platform`;
- `post_id`;
- `post_url`;
- `author`;
- `text`;
- `created_at`;
- `metrics`;
- `links`;
- `github_repo_urls`;
- `comments`;
- `raw_digest`;
- `candidate_only`;
- `serves_truth`.

## Primitive Route

The registered candidate route is:

```text
FacebookSourceSet
  -> candidate.social.facebook_rapidapi_fetch_posts.v0
  -> RawSocialPostSet
  -> candidate.social.normalize_posts.v0
  -> NormalizedSocialPostSet
  -> candidate.social.posts_to_primitive_drafts.v0
  -> PrimitiveDraftSet
```

Search it:

```bash
aidevobserver-fabric search \
  --query "facebook page scraper rapidapi posts primitive drafts" \
  --candidate-only \
  --compact
```

## Review Rules

- Store provider host/path/parameter metadata, not secrets.
- Do not commit live provider configs if they include private account details.
- Do not commit raw scraped pages or raw unreviewed post dumps.
- Treat all extracted primitive drafts as candidate evidence only.
- Keep `serves_truth=false` until review, proof fixtures, and promotion.
