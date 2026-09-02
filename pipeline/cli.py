import logging

import typer

app = typer.Typer(help="Venue insight pipeline", no_args_is_help=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@app.command()
def discover(
    source: list[str] | None = typer.Option(
        None, help="Sources to pull: osm, dohmh (default both)"
    ),
):
    """Pull venue candidates from open sources into raw_venues."""
    from .stages.discover import run_discover

    run_discover(source or ["osm", "dohmh"])


@app.command()
def dedupe():
    """Build canonical venues from raw_venues (deterministic full rebuild)."""
    from .stages.dedupe import run_dedupe

    run_dedupe()


@app.command()
def collect_text(
    posts_per_query: int = typer.Option(50, help="Top posts per (subreddit, keyword) search"),
    min_comments: int = typer.Option(5, help="Skip posts with fewer comments"),
    max_posts: int | None = typer.Option(None, help="Cap on comment trees to fetch this run"),
):
    """Collect Reddit posts and comment trees via the official API into raw_posts/raw_comments."""
    from .stages.collect_text import run_collect_text

    run_collect_text(posts_per_query, min_comments, max_posts)


@app.command()
def collect_reviews(
    source: list[str] | None = typer.Option(
        None, help="wikipedia, wikivoyage, infatuation (default all)"
    ),
    max_pages: int | None = typer.Option(None, help="Cap on Infatuation pages fetched this run"),
):
    """Collect venue reviews/descriptions from open web sources into raw_reviews."""
    from .stages.collect_reviews import run_collect_reviews

    run_collect_reviews(source or ["wikipedia", "wikivoyage", "infatuation"], max_pages)


@app.command()
def match_reviews():
    """Link raw_reviews rows to canonical venues (deterministic, rebuilt each run)."""
    from .stages.match_reviews import run_match_reviews

    run_match_reviews()


@app.command()
def extract_insights(
    limit: int | None = typer.Option(None, help="Max reviews to extract this run"),
    source: list[str] | None = typer.Option(None, help="Restrict to sources"),
    only_matched: bool = typer.Option(True, help="Only reviews linked to a venue"),
):
    """LLM insight extraction per review (resumable; re-extracts only changed text)."""
    from .stages.extract_insights import run_extract_insights

    run_extract_insights(limit, source, only_matched)


@app.command()
def review_sample(
    n: int = typer.Option(30, help="Insights to sample"),
    out_dir: str = typer.Option("reviews", help="Where to write the markdown sample"),
    unreviewed_only: bool = typer.Option(True, help="Skip insights that already have a verdict"),
):
    """Write a markdown sample of extractions for a reviewer (Claude or human)."""
    from pathlib import Path

    from .stages.review_sample import write_sample

    typer.echo(write_sample(n, Path(out_dir), unreviewed_only))


@app.command()
def review_ingest(
    path: str, reviewer: str = typer.Option(..., help="Who reviewed: claude, selwyn, ...")
):
    """Read verdict lines from a reviewed sample file into extraction_reviews."""
    from pathlib import Path

    from .stages.review_sample import ingest

    typer.echo(ingest(Path(path), reviewer))


@app.command()
def scorecard():
    """Print extraction quality metrics from verdicts and the grounding check."""
    import json

    from .stages.review_sample import scorecard as _scorecard

    typer.echo(json.dumps(_scorecard(), indent=2, default=str))


@app.command()
def freshness():
    """Nightly job: re-pull text and re-extract stale venues. (Later stages plug in here.)"""
    typer.echo("freshness: no downstream stages implemented yet")


@app.command()
def status():
    """Show recent runs and progress counts."""
    from .db import connect

    with connect() as conn:
        for r in conn.execute(
            "select id, stage, status, started_at, finished_at, stats from pipeline_runs "
            "order by id desc limit 10"
        ):
            typer.echo(
                f"{r['id']:>4} {r['stage']:<12} {r['status']:<11} {r['started_at']:%Y-%m-%d %H:%M} {r['stats']}"
            )
        for r in conn.execute("select source, count(*) as n from raw_venues group by source"):
            typer.echo(f"raw_venues[{r['source']}] = {r['n']}")
