# Publishing

This repo is designed to be safe to publish as a generalized GitHub project.

## Local Checks

```bash
python -m unittest discover -s tests
python -m aidevobserver_fabric.cli self-test
```

## GitHub Setup

Suggested commands:

```bash
git init
git add .
git commit -m "initial generalized capability fabric"
gh repo create Amarel-Taylor-Scott/aidevobserver-capability-fabric --public --source . --push
```

Use `--private` instead of `--public` if you want to review the repo on GitHub
before making it public.

## Safety Review

Do not publish:

- raw coding transcripts;
- local filesystem inventory;
- credentials;
- private repo paths;
- copied third-party source;
- generated operational logs.
- raw scraped pages from third-party sources unless licensing and attribution
  have been reviewed.
- live RapidAPI provider configs if they contain private account details.
- API keys in JSON examples, docs, tests, logs, request plans, or output files.

The seed examples are synthetic and candidate-only.
