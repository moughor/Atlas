"""Command-line interface for MoughorAI."""

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from moughorai.config import load_config
from moughorai.knowledge import KnowledgeLoaderError
from moughorai.orchestrator import Orchestrator
from moughorai.prompts import PromptBuilderError
from moughorai.rules import (
    RuleLoader,
    RuleLoaderError,
    RuleRepository,
    RuleSelector,
)
from moughorai.services.ollama_service import (
    OllamaConnectionError,
    OllamaResponseError,
    OllamaServiceError,
)

app = typer.Typer(
    name="moughorai",
    help="Local AI software-engineering assistant.",
    no_args_is_help=True,
)

console = Console()
error_console = Console(stderr=True)


@app.callback()
def callback() -> None:
    """Local AI software-engineering assistant."""


def create_orchestrator() -> Orchestrator:
    """Create the fully configured application orchestrator."""

    config = load_config()

    rule_loader = RuleLoader(
        config.workspace_root,
    )
    rule_repository = RuleRepository(
        rule_loader,
        config.brain_path,
        category="general",
    )
    rule_selector = RuleSelector(
        rule_repository,
    )

    return Orchestrator(
        rule_selector=rule_selector,
    )


@app.command()
def ask(
    request: Annotated[
        str,
        typer.Argument(
            help="The request to send to MoughorAI.",
        ),
    ],
    project: Path | None = typer.Option(
        None,
        "--project",
        "-p",
        help="Project directory to analyze.",
        exists=True,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
    ),
) -> None:
    """Send one request through the complete MoughorAI pipeline."""

    try:
        orchestrator = create_orchestrator()
        response = orchestrator.ask(
            request,
            project=project,
        )
    except PromptBuilderError as error:
        error_console.print(
            f"[bold red]Invalid request:[/bold red] {error}"
        )
        raise typer.Exit(code=2) from error
    except FileNotFoundError as error:
        error_console.print(
            f"[bold red]Workspace path error:[/bold red] {error}"
        )
        raise typer.Exit(code=3) from error
    except KnowledgeLoaderError as error:
        error_console.print(
            f"[bold red]Knowledge loading error:[/bold red] {error}"
        )
        raise typer.Exit(code=4) from error
    except RuleLoaderError as error:
        error_console.print(
            f"[bold red]Rule loading error:[/bold red] {error}"
        )
        raise typer.Exit(code=4) from error
    except OllamaConnectionError as error:
        error_console.print(
            "[bold red]Could not connect to Ollama.[/bold red]"
        )
        error_console.print(str(error))
        error_console.print(
            "\nCheck that Ollama is running and that "
            "config/config.yaml contains the correct host."
        )
        raise typer.Exit(code=5) from error
    except OllamaResponseError as error:
        error_console.print(
            f"[bold red]Invalid Ollama response:[/bold red] {error}"
        )
        raise typer.Exit(code=6) from error
    except OllamaServiceError as error:
        error_console.print(
            f"[bold red]Ollama error:[/bold red] {error}"
        )
        raise typer.Exit(code=7) from error

    if not response:
        error_console.print(
            "[bold yellow]Ollama returned an empty response.[/bold yellow]"
        )
        raise typer.Exit(code=8)

    console.print(response)


def main() -> None:
    """Run the MoughorAI command-line application."""

    app()


if __name__ == "__main__":
    main()