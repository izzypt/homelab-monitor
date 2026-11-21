"""Operator CLI: `python -m app.cli <command>`. Commands are added as features land."""

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli", description="homelab-monitor admin CLI")
    parser.add_subparsers(dest="command", metavar="command")
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
