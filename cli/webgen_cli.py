#!/usr/bin/env python3
"""
WebGen CLI — Command-line interface for website generation.
============================================================
Usage:
  python webgen_cli.py generate --name "Acme Corp" --type restaurant
  python webgen_cli.py learn /path/to/site --type agency
  python webgen_cli.py templates
  python webgen_cli.py projects
  python webgen_cli.py types
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Ensure project root on path
sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    import typer
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    HAS_RICH = True
except ImportError:
    HAS_RICH = False

from backend.webgen.models import BusinessType, ClientBrief
from backend.webgen.pipeline import WebGenPipeline

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

if HAS_RICH:
    app = typer.Typer(
        name="webgen",
        help="AI-powered website generation with local LLMs.",
        no_args_is_help=True,
    )
    console = Console()
else:
    app = None
    console = None


def _run(coro):
    """Run async function synchronously."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor() as pool:
            return pool.submit(asyncio.run, coro).result()
    return asyncio.run(coro)


def _get_pipeline() -> WebGenPipeline:
    return WebGenPipeline()


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

if HAS_RICH:

    @app.command()
    def types():
        """List all supported business types."""
        table = Table(title="Supported Business Types")
        table.add_column("Type", style="cyan")
        table.add_column("Value", style="green")
        for bt in BusinessType:
            table.add_row(bt.name, bt.value)
        console.print(table)

    @app.command()
    def templates(business_type: str = typer.Option("", "--type", "-t", help="Filter by business type")):
        """List learned templates."""
        pipeline = _get_pipeline()
        tmps = pipeline.list_templates(business_type)
        if not tmps:
            console.print("[yellow]No templates found. Learn some with 'webgen learn'.[/yellow]")
            return
        table = Table(title=f"Templates ({len(tmps)})")
        table.add_column("ID", style="dim")
        table.add_column("Name", style="cyan")
        table.add_column("Type", style="green")
        table.add_column("Components", justify="right")
        table.add_column("Created")
        for t in tmps:
            table.add_row(t.id, t.name, t.business_type, str(len(t.component_ids)), t.created_at[:10])
        console.print(table)

    @app.command()
    def components(
        category: str = typer.Option("", "--cat", "-c", help="Filter by category"),
        business_type: str = typer.Option("", "--type", "-t", help="Filter by business type"),
    ):
        """List learned components."""
        pipeline = _get_pipeline()
        comps = pipeline.list_components(category, business_type)
        if not comps:
            console.print("[yellow]No components found.[/yellow]")
            return
        table = Table(title=f"Components ({len(comps)})")
        table.add_column("ID", style="dim")
        table.add_column("Name", style="cyan")
        table.add_column("Category", style="green")
        table.add_column("Variables", justify="right")
        table.add_column("Business Types")
        for c in comps:
            table.add_row(c.id, c.name, c.category, str(len(c.variables)), ", ".join(c.business_types))
        console.print(table)

    @app.command()
    def projects():
        """List all site generation projects."""
        pipeline = _get_pipeline()
        projs = pipeline.list_projects()
        if not projs:
            console.print("[yellow]No projects yet. Generate one with 'webgen generate'.[/yellow]")
            return
        table = Table(title=f"Projects ({len(projs)})")
        table.add_column("ID", style="dim")
        table.add_column("Business", style="cyan")
        table.add_column("Type", style="green")
        table.add_column("Status", style="magenta")
        table.add_column("Pages", justify="right")
        table.add_column("Created")
        for p in projs:
            table.add_row(
                p.id,
                p.brief.business_name,
                p.brief.business_type.value,
                p.status.value,
                str(len(p.pages)),
                p.created_at[:10],
            )
        console.print(table)

    @app.command()
    def learn(
        source: str = typer.Argument(..., help="Path to HTML file or directory"),
        business_type: str = typer.Option("custom", "--type", "-t", help="Business type"),
        name: str = typer.Option("", "--name", "-n", help="Template name"),
    ):
        """Learn a template from an existing website directory."""
        pipeline = _get_pipeline()
        console.print(f"[cyan]Learning template from:[/cyan] {source}")

        try:
            template = _run(pipeline.learn_site(source, business_type, name))
            console.print(
                Panel(
                    f"[green]Template learned![/green]\n"
                    f"ID: {template.id}\n"
                    f"Name: {template.name}\n"
                    f"Components: {len(template.component_ids)}\n"
                    f"Sections: {', '.join(template.section_order)}",
                    title="Template Learned",
                )
            )
        except Exception as e:
            console.print(f"[red]Error:[/red] {e}")
            raise typer.Exit(1)

    @app.command()
    def learn_url(
        url: str = typer.Argument(..., help="URL to learn from"),
        business_type: str = typer.Option("custom", "--type", "-t", help="Business type"),
        name: str = typer.Option("", "--name", "-n", help="Template name"),
    ):
        """Learn a template from a website URL."""
        pipeline = _get_pipeline()
        console.print(f"[cyan]Fetching:[/cyan] {url}")

        try:
            import httpx

            resp = httpx.get(url, follow_redirects=True, timeout=30)
            resp.raise_for_status()
            html = resp.text
        except Exception as e:
            console.print(f"[red]Fetch error:[/red] {e}")
            raise typer.Exit(1)

        try:
            template = _run(pipeline.learn_html(html, url, business_type, name))
            console.print(
                Panel(
                    f"[green]Template learned from URL![/green]\n"
                    f"ID: {template.id}\n"
                    f"Name: {template.name}\n"
                    f"Components: {len(template.component_ids)}",
                    title="Template Learned",
                )
            )
        except Exception as e:
            console.print(f"[red]Error:[/red] {e}")
            raise typer.Exit(1)

    @app.command()
    def generate(
        name: str = typer.Option(..., "--name", "-n", help="Business name"),
        business_type: str = typer.Option("custom", "--type", "-t", help="Business type"),
        tagline: str = typer.Option("", "--tagline", help="Business tagline"),
        description: str = typer.Option("", "--desc", help="Business description"),
        services: str = typer.Option("", "--services", "-s", help="Comma-separated services"),
        audience: str = typer.Option("", "--audience", help="Target audience"),
        tone: str = typer.Option("professional", "--tone", help="Site tone"),
        phone: str = typer.Option("", "--phone", help="Phone number"),
        email: str = typer.Option("", "--email", help="Email address"),
        address: str = typer.Option("", "--address", help="Business address"),
        pages: str = typer.Option("", "--pages", help="Comma-separated page slugs"),
        base_url: str = typer.Option("", "--url", help="Base URL for the site"),
        no_export: bool = typer.Option(False, "--no-export", help="Skip file export"),
        tests_ok: bool = typer.Option(False, "--tests-ok", help="Mark test quality gate as passed"),
        playwright_ok: bool = typer.Option(False, "--playwright-ok", help="Mark Playwright quality gate as passed"),
        lighthouse_mobile_ok: bool = typer.Option(
            False,
            "--lighthouse-mobile-ok",
            help="Mark mobile Lighthouse quality gate as passed",
        ),
    ):
        """Generate a complete website from a business brief."""
        # Validate business type
        try:
            bt = BusinessType(business_type)
        except ValueError:
            valid = ", ".join(b.value for b in BusinessType)
            console.print(f"[red]Invalid type.[/red] Valid: {valid}")
            raise typer.Exit(1)

        brief = ClientBrief(
            business_name=name,
            business_type=bt,
            tagline=tagline,
            description=description or f"{name} — {tagline}",
            services=[s.strip() for s in services.split(",") if s.strip()] if services else [],
            target_audience=audience,
            tone=tone,
            phone=phone,
            email=email,
            address=address,
            pages_requested=[p.strip() for p in pages.split(",") if p.strip()] if pages else [],
        )

        pipeline = _get_pipeline()
        console.print(
            Panel(
                f"[cyan]Generating website for:[/cyan] {name}\n"
                f"Type: {bt.value} | Tone: {tone}\n"
                f"Services: {', '.join(brief.services) or 'Auto-detect'}",
                title="WebGen Pipeline",
            )
        )

        try:
            project = _run(
                pipeline.quick_generate(
                    brief,
                    base_url,
                    export=not no_export,
                    quality_checks={
                        "tests_ok": tests_ok,
                        "playwright_ok": playwright_ok,
                        "lighthouse_mobile_ok": lighthouse_mobile_ok,
                    },
                )
            )

            # Summary
            issues = len(project.errors)
            console.print(
                Panel(
                    f"[green]Website generated![/green]\n"
                    f"Project ID: {project.id}\n"
                    f"Pages: {len(project.pages)}\n"
                    f"Status: {project.status.value}\n"
                    f"QA Issues: {issues}\n"
                    f"Output: {project.output_dir}",
                    title="Generation Complete",
                )
            )

            if project.errors:
                console.print("\n[yellow]QA Issues:[/yellow]")
                for err in project.errors[:10]:
                    console.print(f"  - {err}")
                if len(project.errors) > 10:
                    console.print(f"  ... and {len(project.errors) - 10} more")

        except Exception as e:
            console.print(f"[red]Pipeline error:[/red] {e}")
            import traceback

            traceback.print_exc()
            raise typer.Exit(1)

    @app.command()
    def status(project_id: str = typer.Argument(..., help="Project ID")):
        """Show project status and details."""
        pipeline = _get_pipeline()
        project = pipeline.get_project(project_id)
        if not project:
            console.print(f"[red]Project not found:[/red] {project_id}")
            raise typer.Exit(1)

        console.print(
            Panel(
                f"Business: {project.brief.business_name}\n"
                f"Type: {project.brief.business_type.value}\n"
                f"Status: {project.status.value}\n"
                f"Pages: {len(project.pages)}\n"
                f"Templates used: {len(project.template_ids)}\n"
                f"Output: {project.output_dir}\n"
                f"Errors: {len(project.errors)}\n"
                f"Created: {project.created_at}\n"
                f"Updated: {project.updated_at}",
                title=f"Project {project.id}",
            )
        )

        if project.pages:
            table = Table(title="Pages")
            table.add_column("Slug", style="cyan")
            table.add_column("Title")
            table.add_column("Sections", justify="right")
            table.add_column("HTML Size", justify="right")
            for p in project.pages:
                table.add_row(
                    p.slug,
                    p.title,
                    str(len(p.sections)),
                    f"{len(p.html):,}" if p.html else "—",
                )
            console.print(table)

    @app.command()
    def health():
        """Check Ollama connection and model availability."""
        from backend.llm import OllamaClient

        llm = OllamaClient()

        async def _check():
            available = await llm.is_available()
            models = await llm.list_models() if available else []
            await llm.close()
            return available, models

        available, models = _run(_check())

        if available:
            console.print(f"[green]Ollama online[/green] at {llm.base_url}")
            console.print(f"Model: {llm.model}")
            console.print(f"Available models: {', '.join(models)}")
        else:
            console.print(f"[red]Ollama offline[/red] at {llm.base_url}")
            console.print("Start with: ollama serve")


# ---------------------------------------------------------------------------
# Fallback CLI (no typer/rich)
# ---------------------------------------------------------------------------


def _fallback_cli():
    """Minimal CLI when typer/rich are not installed."""
    if len(sys.argv) < 2:
        print("WebGen CLI — Install typer and rich for full experience:")
        print("  pip install typer rich")
        print()
        print("Commands: types, health, generate, learn, templates, projects")
        return

    cmd = sys.argv[1]

    if cmd == "types":
        print("Supported business types:")
        for bt in BusinessType:
            print(f"  {bt.value}")

    elif cmd == "health":
        from backend.llm import OllamaClient

        llm = OllamaClient()
        available = asyncio.run(llm.is_available())
        print(f"Ollama: {'online' if available else 'OFFLINE'} ({llm.base_url})")
        if available:
            models = asyncio.run(llm.list_models())
            print(f"Models: {', '.join(models)}")
        asyncio.run(llm.close())

    else:
        print(f"Unknown command: {cmd}")
        print("Install typer and rich for full CLI: pip install typer rich")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if HAS_RICH and app:
        app()
    else:
        _fallback_cli()
