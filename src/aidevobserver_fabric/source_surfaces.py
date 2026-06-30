"""Curated public source surfaces for AI startup and primitive discovery."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Iterable


@dataclass(frozen=True, slots=True)
class SourceSurface:
    source_id: str
    name: str
    url: str
    category: str
    signal: str
    use_for: str
    cadence: str
    candidate_only: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


SOURCE_SURFACES: tuple[SourceSurface, ...] = (
    # Startup directories and funding signals.
    SourceSurface("startup.yc.ai", "Y Combinator AI Companies", "https://www.ycombinator.com/companies?tags=Artificial%20Intelligence", "startup_directory", "early-stage AI startup directory", "find startups, categories, founder positioning, and repeatable primitive ideas", "weekly"),
    SourceSurface("startup.yc.rfs", "YC Requests for Startups", "https://www.ycombinator.com/rfs", "startup_thesis", "forward-looking startup thesis", "infer emerging primitive families and market gaps", "monthly"),
    SourceSurface("startup.launch_yc", "Launch YC", "https://www.ycombinator.com/launches", "launch_tracker", "new YC launch feed", "detect fresh product patterns before broader coverage", "weekly"),
    SourceSurface("startup.cbinsights.ai100", "CB Insights AI 100", "https://www.cbinsights.com/research/report/artificial-intelligence-top-startups/", "startup_ranking", "curated later-stage private AI startup list", "benchmark market maps and validation signals", "quarterly"),
    SourceSurface("startup.forbes.ai50", "Forbes AI 50", "https://www.forbes.com/lists/ai50/", "startup_ranking", "curated private AI company list", "track high-visibility AI company categories", "quarterly"),
    SourceSurface("startup.sifted.ai100", "Sifted AI 100", "https://sifted.eu/ai-100", "startup_ranking", "European AI startup ranking", "discover non-US startup categories and regional trends", "quarterly"),
    SourceSurface("startup.crunchbase.ai", "Crunchbase News AI", "https://news.crunchbase.com/sections/ai/", "funding_news", "funding and market activity", "track funded startup categories and investor themes", "weekly"),
    SourceSurface("startup.dealroom.ai", "Dealroom AI", "https://dealroom.co/guides/artificial-intelligence", "funding_database", "ecosystem and funding database", "track geography, sectors, funding, and investor signal", "monthly"),
    SourceSurface("startup.startuphubai", "StartupHub.ai", "https://www.startuphub.ai/", "startup_database", "AI startup and investor database", "discover startup categories by sector and investor", "weekly"),
    SourceSurface("startup.topstartups", "TopStartups.io", "https://topstartups.io/", "startup_database", "daily-updated startup tracker", "find funded companies by category, size, and geography", "weekly"),
    SourceSurface("startup.betablist", "BetaList", "https://betalist.com/", "prelaunch_tracker", "prelaunch startup feed", "find very early products and unmet workflows", "weekly"),

    # Launch and product discovery.
    SourceSurface("launch.producthunt.ai", "Product Hunt Artificial Intelligence", "https://www.producthunt.com/topics/artificial-intelligence", "product_launch", "daily product launches", "find new AI apps, wrappers, agents, and user-facing workflows", "daily"),
    SourceSurface("launch.hn.show", "Hacker News Show HN", "https://news.ycombinator.com/show", "builder_launch", "raw technical launches", "find developer-built tools before market polish", "daily"),
    SourceSurface("launch.hn.ask", "Hacker News Ask HN", "https://news.ycombinator.com/ask", "pain_point_feed", "builder/user pain points", "mine repeated workflow problems and negative examples", "daily"),
    SourceSurface("launch.fazier", "Fazier", "https://fazier.com/", "product_launch", "indie and startup launches", "find small AI products and indie builder patterns", "weekly"),
    SourceSurface("launch.uneed", "Uneed", "https://www.uneed.best/", "product_launch", "product launch discovery", "find dev tools, SaaS, and AI product surfaces", "weekly"),

    # AI product and tool directories.
    SourceSurface("tools.futurepedia", "Futurepedia", "https://www.futurepedia.io/", "ai_tool_directory", "large categorized AI tool directory", "discover crowded categories and common capability surfaces", "weekly"),
    SourceSurface("tools.taaft", "There's An AI For That", "https://theresanaiforthat.com/", "ai_tool_directory", "broad AI tools directory", "check whether a workflow already has many AI tools", "weekly"),
    SourceSurface("tools.futuretools", "FutureTools", "https://www.futuretools.io/", "ai_tool_directory", "curated AI tools feed", "discover consumer and productivity AI tools", "weekly"),
    SourceSurface("tools.toolify", "Toolify AI", "https://www.toolify.ai/", "ai_tool_directory", "AI tools directory and traffic ranking", "find categories with many competing products", "weekly"),
    SourceSurface("tools.huggingface.spaces", "Hugging Face Spaces", "https://huggingface.co/spaces", "demo_directory", "AI demos and apps", "discover model-backed demo patterns and prototype primitives", "daily"),
    SourceSurface("tools.openrouter.models", "OpenRouter Models", "https://openrouter.ai/models", "model_marketplace", "model availability and routing surface", "track models developers are integrating", "weekly"),

    # Newsletters and technical feeds.
    SourceSurface("newsletter.tldr_ai", "TLDR AI", "https://tldr.tech/ai", "newsletter", "daily AI news and tools", "daily scan for AI product and research signals", "daily"),
    SourceSurface("newsletter.rundown", "The Rundown AI", "https://www.therundown.ai/", "newsletter", "broad daily AI newsletter", "track mainstream AI launches and workflows", "daily"),
    SourceSurface("newsletter.batch", "The Batch", "https://www.deeplearning.ai/the-batch/", "newsletter", "weekly AI news and analysis", "track technical and market shifts", "weekly"),
    SourceSurface("newsletter.import_ai", "Import AI", "https://importai.substack.com/", "newsletter", "frontier AI research commentary", "identify technical ideas before productization", "weekly"),
    SourceSurface("newsletter.latent_space", "Latent Space", "https://www.latent.space/", "newsletter_podcast", "AI engineering interviews and essays", "track agents, evals, infra, and model-lab patterns", "weekly"),
    SourceSurface("newsletter.interconnects", "Interconnects", "https://www.interconnects.ai/", "newsletter", "frontier and open model analysis", "track post-training, evals, and open model strategy", "weekly"),
    SourceSurface("newsletter.bensbites", "Ben's Bites", "https://www.bensbites.com/", "newsletter", "AI startup and tool digest", "find startup/product discovery leads", "daily"),
    SourceSurface("newsletter.sequence", "The Sequence", "https://thesequence.substack.com/", "newsletter", "ML and AI technical digest", "track ML systems and enterprise AI ideas", "weekly"),
    SourceSurface("newsletter.alphasignal", "AlphaSignal", "https://alphasignal.ai/", "newsletter", "AI research and repo digest", "discover papers, repos, and model releases", "daily"),
    SourceSurface("newsletter.last_week_ai", "Last Week in AI", "https://lastweekin.ai/", "newsletter_podcast", "weekly AI news summary", "catch missed developments and debates", "weekly"),

    # Open-source repo discovery.
    SourceSurface("repo.github.ai_topic", "GitHub AI Topic", "https://github.com/topics/artificial-intelligence", "repo_directory", "public repositories under AI topic", "discover implementation surfaces and open-source primitives", "daily"),
    SourceSurface("repo.github.llm_topic", "GitHub LLM Topic", "https://github.com/topics/large-language-models", "repo_directory", "LLM repositories", "track LLM apps, infra, eval, and agent code", "daily"),
    SourceSurface("repo.github.ai_agents_topic", "GitHub AI Agents Topic", "https://github.com/topics/ai-agents", "repo_directory", "AI agent repositories", "discover agent patterns, tools, and orchestration code", "daily"),
    SourceSurface("repo.ossinsight.ai", "OSSInsight AI Collection", "https://ossinsight.io/collections/ai/", "repo_trending", "open-source AI trending dashboard", "rank repos by live open-source momentum", "weekly"),
    SourceSurface("repo.paperswithcode", "Papers with Code", "https://paperswithcode.com/", "research_code_directory", "papers, code, datasets, leaderboards", "connect research methods to code and benchmarks", "weekly"),
    SourceSurface("repo.huggingface.models", "Hugging Face Models", "https://huggingface.co/models", "model_directory", "model repository and metadata", "discover reusable models and capability classes", "daily"),
    SourceSurface("repo.huggingface.datasets", "Hugging Face Datasets", "https://huggingface.co/datasets", "dataset_directory", "dataset repository", "find benchmark and fixture candidates", "weekly"),
    SourceSurface("repo.mcp.servers", "Model Context Protocol Servers", "https://github.com/modelcontextprotocol/servers", "tool_registry", "reference MCP server implementations", "discover agent tool surfaces and schemas", "weekly"),
    SourceSurface("repo.awesome_mcp", "Awesome MCP Servers", "https://github.com/punkpeye/awesome-mcp-servers", "tool_registry", "community MCP server directory", "discover agent tool integrations", "weekly"),
    SourceSurface("repo.awesome_llm_apps", "Awesome LLM Apps", "https://github.com/Shubhamsaboo/awesome-llm-apps", "repo_list", "LLM app templates and examples", "mine reusable app patterns and primitives", "weekly"),
    SourceSurface("repo.awesome_ai_agents", "Awesome AI Agents", "https://github.com/e2b-dev/awesome-ai-agents", "repo_list", "AI agent projects", "track agent architectures and open-source examples", "weekly"),
    SourceSurface("repo.awesome_llm", "Awesome LLM", "https://github.com/Hannibal046/Awesome-LLM", "repo_list", "LLM papers, tools, and resources", "broad LLM ecosystem discovery", "monthly"),

    # Research, benchmarks, and model eval.
    SourceSurface("research.hf_papers", "Hugging Face Daily Papers", "https://huggingface.co/papers", "paper_feed", "daily trending ML papers", "spot methods likely to become tools", "daily"),
    SourceSurface("research.arxiv_ai", "arXiv cs.AI", "https://arxiv.org/list/cs.AI/recent", "paper_feed", "AI research feed", "raw research discovery", "daily"),
    SourceSurface("research.arxiv_lg", "arXiv cs.LG", "https://arxiv.org/list/cs.LG/recent", "paper_feed", "machine learning research feed", "raw ML method discovery", "daily"),
    SourceSurface("research.semantic_scholar", "Semantic Scholar", "https://www.semanticscholar.org/", "paper_search", "AI-assisted literature search", "trace papers, citations, and related work", "weekly"),
    SourceSurface("bench.lmarena", "LM Arena Leaderboard", "https://lmarena.ai/", "model_benchmark", "community model comparison", "track model quality signals", "weekly"),
    SourceSurface("bench.artificial_analysis", "Artificial Analysis", "https://artificialanalysis.ai/", "model_benchmark", "model intelligence, speed, cost, and latency", "compare provider/model tradeoffs", "weekly"),
    SourceSurface("bench.open_llm_leaderboard", "Open LLM Leaderboard", "https://huggingface.co/spaces/open-llm-leaderboard/open_llm_leaderboard", "model_benchmark", "open model evaluations", "track open model capability baselines", "weekly"),
    SourceSurface("bench.stanford_ai_index", "Stanford AI Index", "https://aiindex.stanford.edu/report/", "annual_report", "AI progress, economics, and policy report", "macro trend validation", "quarterly"),
    SourceSurface("bench.swebench", "SWE-bench", "https://www.swebench.com/", "coding_benchmark", "software engineering benchmark", "evaluate coding-agent claims and examples", "monthly"),
    SourceSurface("bench.aider", "Aider LLM Leaderboards", "https://aider.chat/docs/leaderboards/", "coding_benchmark", "coding model leaderboard", "compare coding model performance for agent workflows", "weekly"),

    # VC, market maps, and thesis sources.
    SourceSurface("vc.a16z_ai", "a16z AI", "https://a16z.com/ai/", "vc_thesis", "AI essays, podcasts, and market commentary", "track investor thesis and market maps", "monthly"),
    SourceSurface("vc.a16z_ai_canon", "a16z AI Canon", "https://a16z.com/ai-canon/", "resource_collection", "AI papers, posts, courses, guides", "learn canonical concepts and source ideas", "monthly"),
    SourceSurface("vc.sequoia_ai_ascent", "Sequoia AI Ascent", "https://www.sequoiacap.com/events/ai-ascent/", "event_thesis", "AI founder/researcher event content", "track agentic software and startup themes", "monthly"),
    SourceSurface("vc.menlo_ai", "Menlo Ventures AI", "https://menlovc.com/inflection-points-ai/", "vc_thesis", "AI infrastructure and enterprise views", "track AI infra startup categories", "monthly"),
    SourceSurface("vc.bessemer_cloud_ai", "Bessemer State of Cloud", "https://www.bvp.com/atlas/state-of-the-cloud", "vc_report", "cloud and AI market report", "enterprise AI and SaaS trend validation", "quarterly"),
    SourceSurface("vc.conviction", "Conviction", "https://www.conviction.com/", "vc_portfolio", "AI-native venture lens", "discover early AI-native company themes", "monthly"),
    SourceSurface("vc.radical", "Radical Ventures Portfolio", "https://radical.vc/portfolio/", "vc_portfolio", "AI-focused venture portfolio", "discover AI companies across infra, robotics, biotech, and data", "monthly"),
    SourceSurface("vc.greylock_ai", "Greylock AI", "https://greylock.com/greymatter/?category=artificial-intelligence", "vc_thesis", "enterprise and AI company commentary", "track product theses and founder interviews", "monthly"),

    # News and reporting.
    SourceSurface("news.techcrunch_ai", "TechCrunch AI", "https://techcrunch.com/category/artificial-intelligence/", "news", "AI startup and product coverage", "track launches, funding, and acquisitions", "daily"),
    SourceSurface("news.venturebeat_ai", "VentureBeat AI", "https://venturebeat.com/category/ai/", "news", "enterprise AI and data coverage", "track enterprise AI adoption and tools", "daily"),
    SourceSurface("news.sifted_ai", "Sifted AI", "https://sifted.eu/sections/ai", "news", "European AI startup news", "track EU startup and funding signals", "weekly"),
    SourceSurface("news.the_information_ai", "The Information AI", "https://www.theinformation.com/artificial-intelligence", "paid_news", "model lab and startup business reporting", "deep business strategy signal", "weekly"),
    SourceSurface("news.ai_business", "AI Business", "https://aibusiness.com/", "news", "enterprise AI implementation coverage", "enterprise deployment patterns", "weekly"),

    # Communities and events.
    SourceSurface("community.ai_engineer", "AI Engineer", "https://www.ai.engineer/", "community_event", "AI engineering community and events", "track production AI engineering practices", "weekly"),
    SourceSurface("community.huggingface", "Hugging Face Community", "https://huggingface.co/join/discord", "community", "open-source AI community", "discover builders, Spaces, models, and datasets", "monthly"),
    SourceSurface("community.latent_space", "Latent Space Community", "https://www.latent.space/", "community", "AI engineering community", "track engineers, founders, and infra builders", "weekly"),
    SourceSurface("community.reddit_localllama", "r/LocalLLaMA", "https://www.reddit.com/r/LocalLLaMA/", "community", "local and open model community", "track open model tooling and deployment patterns", "daily"),
    SourceSurface("community.hackernews", "Hacker News", "https://news.ycombinator.com/", "community", "technical founder and builder forum", "launch and pain-point discovery", "daily"),
)


def grouped_surfaces(surfaces: Iterable[SourceSurface] = SOURCE_SURFACES) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for surface in surfaces:
        grouped.setdefault(surface.category, []).append(surface.to_dict())
    return dict(sorted(grouped.items()))


def as_json(surfaces: Iterable[SourceSurface] = SOURCE_SURFACES) -> str:
    surface_tuple = tuple(surfaces)
    return json.dumps(
        {
            "catalog_id": "aidevobserver.source_surfaces.v0",
            "serves_truth": False,
            "record_count": len(surface_tuple),
            "categories": grouped_surfaces(surface_tuple),
        },
        indent=2,
        sort_keys=True,
    ) + "\n"


def as_compact(surfaces: Iterable[SourceSurface] = SOURCE_SURFACES) -> str:
    lines = [
        "AIDevObserver source surfaces",
        "BOUNDARY candidate_intake=true serves_truth=false",
    ]
    for surface in surfaces:
        lines.append(
            f"SRC {surface.source_id} cat:{surface.category} cadence:{surface.cadence} "
            f"use:{surface.use_for} url:{surface.url}"
        )
    return "\n".join(lines) + "\n"
