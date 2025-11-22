import argparse

from code_agent.tracking import BugHunterNotebook


def clear_command(args: argparse.Namespace) -> None:
    notebook = BugHunterNotebook(path=args.state_dir)
    notebook.clear()
    print("Cleared all entrypoints and POTENTIAL bugs.")


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="code-agent",
        description="CLI for managing the code-agent bug hunter",
    )
    parser.add_argument(
        "--state-dir",
        help="Path to the state directory",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "clear",
        help="Remove all entrypoints and bugs with POTENTIAL status",
    )

    return parser


def run_cli(args: list[str] | None = None) -> None:
    parser = create_parser()
    parsed = parser.parse_args(args)

    if parsed.command == "clear":
        clear_command(parsed)
