## `utils/search.py`

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fnmatch
import re
import sys
from pathlib import Path
from typing import Iterable

EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
}

DEFAULT_INCLUDE = ["*.py", "*.toml", "*.md", "*.txt", "*.json", "*.yaml", "*.yml", "*.sh"]


def is_excluded(path: Path) -> bool:
    return any(part in EXCLUDED_DIRS for part in path.parts)


def iter_files(base: Path, include_patterns: list[str]) -> Iterable[Path]:
    if base.is_file():
        if not is_excluded(base) and any(fnmatch.fnmatch(base.name, pat) for pat in include_patterns):
            yield base
        return

    for path in base.rglob("*"):
        if not path.is_file():
            continue
        if is_excluded(path):
            continue
        if any(fnmatch.fnmatch(path.name, pat) for pat in include_patterns):
            yield path


def search_text(
    pattern: str,
    base: Path,
    ignore_case: bool,
    context: int,
    include: list[str],
    use_regex: bool,
) -> int:
    if use_regex:
        flags = re.IGNORECASE if ignore_case else 0
        try:
            matcher = re.compile(pattern, flags)
        except re.error as e:
            print(f"Invalid regex: {e}", file=sys.stderr)
            return 2

        def matches(line: str) -> bool:
            return bool(matcher.search(line))
    else:
        needle = pattern.casefold() if ignore_case else pattern

        def matches(line: str) -> bool:
            hay = line.casefold() if ignore_case else line
            return needle in hay

    total_matches = 0

    for file_path in iter_files(base, include):
        try:
            lines = file_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except Exception:
            continue

        file_hits = []
        for line_num, line in enumerate(lines, start=1):
            if matches(line):
                file_hits.append(line_num)

        if not file_hits:
            continue

        print(f"\n{file_path}")
        for line_num in file_hits:
            start = max(1, line_num - context)
            end = min(len(lines), line_num + context)

            for n in range(start, end + 1):
                marker = ">" if n == line_num else " "
                print(f"{marker} {n:6} | {lines[n - 1]}")
            print()

        total_matches += len(file_hits)

    if total_matches == 0:
        print("No matches found.")
    else:
        print(f"\n{total_matches} match(es) found.")

    return 0


def search_files(pattern: str, base: Path) -> int:
    found = 0
    for path in iter_files(base, ["*"]):
        if fnmatch.fnmatch(path.name, pattern) or fnmatch.fnmatch(str(path), pattern):
            print(path)
            found += 1

    if found == 0:
        print("No files found.")
    else:
        print(f"\n{found} file(s) found.")
    return 0


def replace_text(find: str, replace: str, base: Path, dry_run: bool, force: bool, include: list[str]) -> int:
    needle = find

    targets: list[Path] = []
    for file_path in iter_files(base, include):
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if needle in content:
            targets.append(file_path)

    if not targets:
        print("No matches found.")
        return 0

    print("Files with matches:")
    for t in targets:
        print(f"  {t}")

    if dry_run:
        print("\n[dry-run] No files changed.")
        return 0

    if not force:
        answer = input("\nProceed with replacement? [y/N] ").strip().lower()
        if answer != "y":
            print("Aborted.")
            return 0

    for file_path in targets:
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
            updated = content.replace(find, replace)
            file_path.write_text(updated, encoding="utf-8")
        except Exception as e:
            print(f"Failed to update {file_path}: {e}", file=sys.stderr)

    print("\nReplacement complete.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="search.py",
        description="Project search helper",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_text = sub.add_parser("text", help="Search file contents")
    p_text.add_argument("pattern", help="Text or regex to search for")
    p_text.add_argument("path", nargs="?", default=".", help="Path to search")
    p_text.add_argument("--ignore-case", "-i", action="store_true", help="Case-insensitive search")
    p_text.add_argument("--context", "-C", type=int, default=1, help="Lines of context around each match")
    p_text.add_argument(
        "--type",
        dest="include",
        default=",".join(DEFAULT_INCLUDE),
        help="Comma-separated file globs (default: common code/docs types)",
    )
    p_text.add_argument("--regex", action="store_true", help="Treat pattern as a regex")

    p_files = sub.add_parser("files", help="Find files by filename glob")
    p_files.add_argument("pattern", help="Filename glob to search for")
    p_files.add_argument("path", nargs="?", default=".", help="Path to search")

    p_replace = sub.add_parser("replace", help="Find and replace across files")
    p_replace.add_argument("find", help="Text to find")
    p_replace.add_argument("replace", help="Replacement text")
    p_replace.add_argument("path", nargs="?", default=".", help="Path to search")
    p_replace.add_argument("--dry-run", action="store_true", help="Preview changes only")
    p_replace.add_argument("--force", action="store_true", help="Skip confirmation")
    p_replace.add_argument(
        "--type",
        dest="include",
        default=",".join(DEFAULT_INCLUDE),
        help="Comma-separated file globs to include",
    )

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "text":
        include = [p.strip() for p in args.include.split(",") if p.strip()]
        return search_text(
            pattern=args.pattern,
            base=Path(args.path),
            ignore_case=args.ignore_case,
            context=args.context if args.context else 1,
            include=include,
            use_regex=args.regex,
        )

    if args.command == "files":
        return search_files(args.pattern, Path(args.path))

    if args.command == "replace":
        include = [p.strip() for p in args.include.split(",") if p.strip()]
        return replace_text(
            find=args.find,
            replace=args.replace,
            base=Path(args.path),
            dry_run=args.dry_run,
            force=args.force,
            include=include,
        )

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
