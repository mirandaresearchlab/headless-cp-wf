"""Tests of scripts/check-comment-spacing.py, the check of the comment layout rule.

The rule: every block of full-line comments has an empty line above its first line.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts" / "check-comment-spacing.py"


def check(path, text):
    """Write text to a file, run the checker on it, and return the finished process.

    Parameters
    ----------
    path : pathlib.Path
        The file to write and check. Its extension decides the language.
    text : str
        The content of the file.

    Returns
    -------
    subprocess.CompletedProcess
        The finished checker, with its exit code and its output.
    """
    path.write_text(text, encoding="utf-8")
    return subprocess.run([sys.executable, str(CHECKER), str(path)], capture_output=True, text=True)


def test_comment_block_directly_after_code_is_reported(tmp_path):
    """Check that the checker reports a comment directly after a code line, with exit code 1 and the line.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder from pytest, removed after the test.
    """
    result = check(tmp_path / "a.sh", "echo one\n# Explain the next step.\necho two\n")
    assert result.returncode == 1
    assert "a.sh:2: comment block has no empty line above it" in result.stdout


def test_comment_block_with_empty_line_above_passes(tmp_path):
    """Check that an empty line above the first line of a block is enough.

    The lines inside the block may follow each other directly.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder from pytest, removed after the test.
    """
    text = "echo one\n\n# First line of the block.\n# Second line of the block.\necho two\n"
    result = check(tmp_path / "b.sh", text)
    assert result.returncode == 0, result.stdout


def test_hash_inside_a_python_string_is_not_a_comment(tmp_path):
    """Check that a '#' inside a Python string does not count as a comment.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder from pytest, removed after the test.
    """
    text = 'SCRIPT = """#!/bin/bash\n# not a comment, part of the string\n"""\nx = 1  # end-of-line comment\n'
    result = check(tmp_path / "c.py", text)
    assert result.returncode == 0, result.stdout


def test_directives_are_not_comments(tmp_path):
    """Check that shebang and #SBATCH lines can follow other lines directly.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder from pytest, removed after the test.
    """
    text = "#!/bin/bash\n#SBATCH -n 1\n#SBATCH -c 2\n\nset -e\n"
    result = check(tmp_path / "d.sbatch", text)
    assert result.returncode == 0, result.stdout


def test_fix_adds_the_missing_empty_line_and_the_file_then_passes(tmp_path):
    """Check that --fix adds the empty line above a comment block, and that the file then passes.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder from pytest, removed after the test.
    """
    path = tmp_path / "e.sh"
    path.write_text("echo one\n# First line.\n# Second line.\necho two\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(CHECKER), "--fix", str(path)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout
    assert path.read_text(encoding="utf-8") == "echo one\n\n# First line.\n# Second line.\necho two\n"


def test_fix_leaves_a_python_comment_at_the_top_of_a_block(tmp_path):
    """Check that --fix does not touch a comment right after a line with a colon, and still reports it.

    Ruff removes an empty line at the start of a block, so a fix there would start a loop of changes.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder from pytest, removed after the test.
    """
    path = tmp_path / "f.py"
    text = "def f():\n    # Comment at the top.\n    return 1\n"
    path.write_text(text, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(CHECKER), "--fix", str(path)], capture_output=True, text=True
    )
    assert result.returncode == 1
    assert path.read_text(encoding="utf-8") == text
