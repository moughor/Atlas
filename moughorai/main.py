import typer
from rich.console import Console

app = typer.Typer(
    name="moughorai",
    help="Local AI engineering assistant powered by Ollama.",
    no_args_is_help=True,
)

console = Console()


@app.callback()
def main() -> None:
    """MoughorAI command-line interface."""


@app.command()
def ask(
    question: str = typer.Argument(..., help="Question to send to MoughorAI."),
) -> None:
    """Ask MoughorAI a question."""
    console.print(f"[bold green]MoughorAI received:[/bold green] {question}")
    console.print(
        "[yellow]The Ollama connection has not been implemented yet.[/yellow]"
    )


if __name__ == "__main__":
    app()
