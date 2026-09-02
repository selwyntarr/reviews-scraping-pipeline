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
