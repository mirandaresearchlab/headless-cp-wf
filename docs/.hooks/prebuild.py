"""MkDocs hook: make the generated reference pages before every build.

MkDocs runs this hook for `mkdocs build` and `mkdocs serve` (see `hooks:` in mkdocs.yml). It makes:
  - reference/parameters.md from nextflow_schema.json (gen_nextflow_params.py),
  - reference/cli.md from the --help text of the commands in `extra.cli_commands` (gen_cli_reference.py),
and copies notebooks from `extra.notebooks_dir` into docs/notebooks/ (this repository has none).

The hook writes a file only when its content changes. Thus `mkdocs serve` does not rebuild in a loop.
"""

import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def _write_if_changed(path, text):
    """Write text to a file, but only if the file does not already hold exactly this text.

    Parameters
    ----------
    path : str
        The file to write. The function makes its folder if needed.
    text : str
        The new content.
    """
    old = None
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            old = fh.read()
    if old != text:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)


def _run(script, *args):
    """Run a generator script from this folder and return its output.

    Parameters
    ----------
    script : str
        File name of the script, for example "gen_cli_reference.py".
    *args : str
        The arguments of the script.

    Returns
    -------
    str
        What the script printed (the Markdown page).

    Raises
    ------
    RuntimeError
        If the script fails. The build then stops with the error of the script.
    """
    res = subprocess.run([sys.executable, os.path.join(HERE, script), *args], capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"{script} failed:\n{res.stderr}")
    return res.stdout


def _same_bytes(first, second):
    """Tell if two files have the same content.

    Parameters
    ----------
    first : str
        Path of the first file.
    second : str
        Path of the second file.

    Returns
    -------
    bool
        True if both files exist and hold the same bytes.
    """
    if not (os.path.exists(first) and os.path.exists(second)):
        return False
    with open(first, "rb") as a, open(second, "rb") as b:
        return a.read() == b.read()


def on_pre_build(config, **kwargs):
    """Make the generated pages before MkDocs reads the documentation.

    Parameters
    ----------
    config : mkdocs.config.defaults.MkDocsConfig
        The MkDocs configuration. The function reads docs_dir, config_file_path and extra.
    **kwargs : dict
        Other arguments from MkDocs (not used).
    """
    docs = config["docs_dir"]
    root = os.path.dirname(config["config_file_path"])
    extra = config.get("extra", {}) or {}

    # Parameter reference, from the schema.
    schema = os.path.join(root, "nextflow_schema.json")
    params_page = os.path.join(docs, "reference", "parameters.md")
    if os.path.exists(schema) and os.path.exists(params_page):
        _write_if_changed(params_page, _run("gen_nextflow_params.py", schema))

    # Command-line reference, from the --help text of each command.
    cli_page = os.path.join(docs, "reference", "cli.md")
    cmds = extra.get("cli_commands") or []
    if cmds and os.path.exists(cli_page):
        _write_if_changed(cli_page, _run("gen_cli_reference.py", "--cwd", root, *cmds))

    # Notebooks: copy each changed notebook into docs/notebooks/.
    nb_dir = extra.get("notebooks_dir")
    if nb_dir and os.path.isdir(os.path.join(root, nb_dir)):
        dest = os.path.join(docs, "notebooks")
        os.makedirs(dest, exist_ok=True)
        for name in sorted(os.listdir(os.path.join(root, nb_dir))):
            src = os.path.join(root, nb_dir, name)
            dst = os.path.join(dest, name)
            if name.endswith(".ipynb") and not _same_bytes(src, dst):
                shutil.copyfile(src, dst)
