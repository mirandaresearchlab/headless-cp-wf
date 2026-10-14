#!/usr/bin/env python3
"""Make the Markdown parameter reference from nextflow_schema.json, and print it.

The schema can use nf-schema / nf-core style groups: draft-07 `definitions` or 2020-12 `$defs`.
docs/.hooks/prebuild.py runs this script on each docs build.

Examples
--------
python gen_nextflow_params.py nextflow_schema.json > docs/reference/parameters.md
"""

import json
import sys


def esc(text):
    """Make a text safe for one cell of a Markdown table.

    Parameters
    ----------
    text : object
        The text (converted with str).

    Returns
    -------
    str
        The text with "|" escaped and line breaks replaced by spaces.
    """
    return str(text).replace("|", "\\|").replace("\n", " ").strip()


def fmt_default(v):
    """Show a default value as inline code.

    Parameters
    ----------
    v : object
        The default from the schema, or None.

    Returns
    -------
    str
        For example "`false`", "`results`", '`""`', or "" for None.
    """
    if v is None:
        return ""
    if isinstance(v, bool):
        return f"`{str(v).lower()}`"
    if isinstance(v, str) and v == "":
        return '`""`'
    return f"`{json.dumps(v) if not isinstance(v, str) else v}`"


def fmt_type(p):
    """Show the type of a parameter, with its allowed values, format, pattern and limits.

    Parameters
    ----------
    p : dict
        The JSON schema of the parameter.

    Returns
    -------
    str
        For example "string<br><small>one of `copy`, `link`</small>".
    """
    t = p.get("type", "")
    if isinstance(t, list):
        t = " / ".join(t)
    extra = []
    if "enum" in p:
        extra.append("one of " + ", ".join(f"`{e}`" for e in p["enum"]))
    if p.get("format") in ("file-path", "directory-path", "path"):
        extra.append(p["format"])
    if "pattern" in p:
        extra.append(f"pattern `{esc(p['pattern'])}`")
    for k, sym in (("minimum", "≥"), ("maximum", "≤")):
        if k in p:
            extra.append(f"{sym} {p[k]}")
    return esc(t) + (f"<br><small>{esc('; '.join(extra))}</small>" if extra else "")


def table(props, required):
    """Make a Markdown table of parameters.

    Parameters
    ----------
    props : dict
        ``{name: JSON schema of the parameter}``.
    required : list of str
        The names of the required parameters.

    Returns
    -------
    str
        The table: one row per parameter with name, type, default and description.
    """
    rows = ["| Parameter | Type | Default | Description |", "|---|---|---|---|"]
    for name, p in props.items():
        req = " **(required)**" if name in required else ""
        desc = esc(p.get("description", ""))
        if p.get("help_text"):
            desc += f"<br><small>{esc(p['help_text'])}</small>"
        rows.append(f"| `--{name}`{req} | {fmt_type(p)} | {fmt_default(p.get('default'))} | {desc} |")
    return "\n".join(rows)


def main():
    """Read the schema given on the command line and print the parameter page."""
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    with open(sys.argv[1], encoding="utf-8") as fh:
        schema = json.load(fh)
    groups = schema.get("$defs") or schema.get("definitions") or {}
    out = [
        "# Parameters",
        "",
        "<!-- GENERATED from nextflow_schema.json by gen_nextflow_params.py: "
        "edit the schema, not this page. -->",
        "",
    ]
    if schema.get("description"):
        out += [esc(schema["description"]), ""]
    out += [
        "Pass parameters on the command line (`--name value`) or in a file with `-params-file params.yml`.",
        "",
    ]

    # One section per group. Hidden parameters go into a folded box at the end.
    seen = set()
    hidden = []
    for gid, g in groups.items():
        props = g.get("properties", {})
        vis = {k: v for k, v in props.items() if not v.get("hidden")}
        hidden += [(k, v, g.get("required", [])) for k, v in props.items() if v.get("hidden")]
        seen.update(props)
        if not vis:
            continue
        out += [f"## {g.get('title', gid)}", ""]
        if g.get("description"):
            out += [esc(g["description"]), ""]
        out += [table(vis, g.get("required", [])), ""]

    # Parameters outside the groups.
    top = {k: v for k, v in schema.get("properties", {}).items() if k not in seen}
    if top:
        out += ["## Other parameters", "", table(top, schema.get("required", [])), ""]
    if hidden:
        out += ['??? note "Hidden / advanced parameters"', ""]
        tbl = table({k: v for k, v, _ in hidden}, sum((r for _, _, r in hidden), []))
        out += ["    " + line for line in tbl.splitlines()] + [""]
    if not groups and not top:
        out += ["!!! warning", "    No parameters found in the schema.", ""]
    print("\n".join(out))


if __name__ == "__main__":
    main()
