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

RapidAPI providers differ in endpoint paths, query parameter names, and response
shapes. Store those details in the provider JSON instead of hard-coding them in
Python.

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

## Scrape

After creating a real provider JSON:

```bash
export RAPIDAPI_KEY="..."

aidevobserver-fabric rapidapi-scrape \
  --provider-config local/facebook_provider.json \
  --sources examples/facebook_sources.json \
  --limit 10 \
  --out generated/facebook_posts.normalized.json
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

