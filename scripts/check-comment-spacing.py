#!/usr/bin/env python3
"""Check the comment layout of the project's code files.

House rule: every block of full-line comments has an empty line directly above its first line. The
lines of one block stay together, without empty lines between them. You can put a comment at the end of a
code line anywhere.

These lines are directives, not comments, so the rule ignores them: a "#!" first line, "#SBATCH"
lines and Docker's "# syntax=" line.

With --fix, the script adds the missing empty lines itself. It does not fix a Python comment that is
the first line inside a block (right after a line that ends with a colon). Ruff removes an empty line
there, so you must move that comment above the block line.

Usage: scripts/check-comment-spacing.py [--fix] [FILE ...]   (no files = all code files of the repository)
Exit code 0 = all files follow the rule (after the fixes, with --fix).
Exit code 1 = at least one comment block has no empty line above it.
"""

import io
import subprocess
import sys
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Folders of coding-agent skills: not workflow code, so the rule does not cover them.
AGENT_FOLDERS = (".claude/", ".agent/")

# Files that use "//" comments (Groovy). Lines that start with "#" in these files are bash comments
# inside a process script block, so they count as comments too.
SLASH_FILES = {".nf", ".config"}

# Files that use "#" comments.
HASH_FILES = {".py", ".sh", ".sbatch", ".yml", ".yaml", ".toml", ".example"}
HASH_NAMES = {"Dockerfile"}

DIRECTIVES = ("#!", "#SBATCH", "# syntax=")


def python_comment_lines(text):
    """Find the comment-only lines of Python code with the Python tokenizer.

    The tokenizer knows strings, so a "#" inside a string does not count.

    Parameters
    ----------
    text : str
        The Python source code.

    Returns
    -------
    set of int
        The numbers (1-based) of the lines that hold only a comment.
    """
    lines = set()
    for token in tokenize.generate_tokens(io.StringIO(text).readline):
        if token.type == tokenize.COMMENT and token.line.strip().startswith("#"):
            lines.add(token.start[0])
    return lines


def text_comment_lines(text, markers):
    """Find the lines that start with a comment marker.

    Parameters
    ----------
    text : str
        The content of the file.
    markers : tuple of str
        The comment markers, for example ("#",) or ("//", "/*", "*", "#").

    Returns
    -------
    set of int
        The numbers (1-based) of the lines whose first characters (after spaces) are a marker.
    """
    return {
        number for number, line in enumerate(text.splitlines(), start=1) if line.strip().startswith(markers)
    }


def comment_lines(path, text):
    """Find the comment-only lines of a file, with the method for its language.

    Parameters
    ----------
    path : pathlib.Path
        The file. Its extension decides the language.
    text : str
        The content of the file.

    Returns
    -------
    set of int
        The numbers (1-based) of the comment-only lines.
    """
    if path.suffix == ".py":
        return python_comment_lines(text)
    if path.suffix in SLASH_FILES:
        return text_comment_lines(text, ("//", "/*", "*", "#"))
    return text_comment_lines(text, ("#",))


def missing_lines(path):
    """Find the comment blocks that have no empty line above them.

    Parameters
    ----------
    path : pathlib.Path
        The file to check.

    Returns
    -------
    list of int
        The numbers (1-based) of the first lines of these blocks.
    """
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    comments = {
        number for number in comment_lines(path, text) if not lines[number - 1].strip().startswith(DIRECTIVES)
    }
    found = []

    # The first line of a file needs nothing above it. Lines inside a block follow another comment.
    for number in sorted(comments):
        if number == 1 or number - 1 in comments:
            continue
        if lines[number - 2].strip():
            found.append(number)
    return found


def check(path):
    """Check the comment layout of one file.

    Parameters
    ----------
    path : pathlib.Path
        The file to check.

    Returns
    -------
    list of str
        One message for each comment block that has no empty line above it.
        Each message has the form "<file>:<line>: comment block has no empty line above it".
    """

    # Show the path relative to the repository when the file is in it, else the full path.
    shown = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
    return [f"{shown}:{number}: comment block has no empty line above it" for number in missing_lines(path)]


def fix(path):
    """Add the missing empty lines to one file.

    The function does not change a Python comment right after a line that ends with a colon. Ruff
    removes an empty line there, so the two tools would undo each other.

    Parameters
    ----------
    path : pathlib.Path
        The file to change.

    Returns
    -------
    int
        The number of empty lines that the function added.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    added = 0

    # Go from the end to the start, so that an insert does not change the numbers of the lines above.
    for number in reversed(missing_lines(path)):
        if path.suffix == ".py" and lines[number - 2].rstrip().endswith(":"):
            continue
        lines.insert(number - 1, "")
        added += 1
    if added:
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return added


def default_files():
    """List all tracked and new code files of the repository, without the agent folders (.claude/, .agent/).

    Returns
    -------
    list of pathlib.Path
        The files from ``git ls-files --cached --others --exclude-standard``.
    """
    names = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    return [ROOT / name for name in names if not name.startswith(AGENT_FOLDERS)]


def in_agent_folder(path):
    """Tell if a file is in an agent skill folder. The rule does not cover these files.

    Pre-commit gives the file names to the script, so default_files() does not filter them.

    Parameters
    ----------
    path : pathlib.Path
        The file.

    Returns
    -------
    bool
        True if the file is in .claude/ or .agent/ of the repository.
    """
    return path.is_relative_to(ROOT) and path.relative_to(ROOT).as_posix().startswith(AGENT_FOLDERS)


def is_code_file(path):
    """Tell if the rule covers a file.

    Parameters
    ----------
    path : pathlib.Path
        The file.

    Returns
    -------
    bool
        True for the file types in SLASH_FILES, HASH_FILES and HASH_NAMES.
    """
    return path.suffix in SLASH_FILES | HASH_FILES or path.name in HASH_NAMES


def main(arguments):
    """Check the given files (or all code files). Print one line per problem.

    Parameters
    ----------
    arguments : list of str
        File paths from the command line. An empty list means all code files. The option --fix
        adds the missing empty lines before the check.

    Returns
    -------
    int
        The exit code: 0 if all files follow the rule, 1 if not.
    """
    do_fix = "--fix" in arguments
    names = [name for name in arguments if name != "--fix"]
    files = [Path(name).resolve() for name in names] or default_files()
    files = [path for path in files if is_code_file(path) and path.is_file() and not in_agent_folder(path)]
    if do_fix:
        for path in files:
            if fix(path):
                print(f"fixed {path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}")
    problems = [problem for path in files for problem in check(path)]
    for problem in problems:
        print(problem)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
