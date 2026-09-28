"""The markdown report as one self-contained HTML page.

Rendered from the markdown rather than from the records, so there is one report and two
spellings of it: a figure cannot be right in one and wrong in the other. The converter knows
only what `report.build` writes — headings, pipe tables, bullet lists, paragraphs, inline
code and bold — and is stdlib-only for the reason `pyproject.toml` gives for every
dependency. No script, no external stylesheet, no font: the page opens from a USB stick in a
conference room with no network, which is where it gets shown.
"""

from __future__ import annotations

import html
import re

_CSS = """
body{font:15px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;margin:2rem auto;
max-width:72rem;padding:0 1rem;color:#1b1f24;background:#fff}
h1{font-size:1.6rem;border-bottom:2px solid #d0d7de;padding-bottom:.3rem}
h2{font-size:1.2rem;margin-top:2rem}
table{border-collapse:collapse;margin:.6rem 0 1rem;font-size:.9rem}
th,td{border:1px solid #d0d7de;padding:.3rem .6rem;text-align:left;vertical-align:top}
th{background:#f6f8fa}
tr:nth-child(even) td{background:#fbfcfd}
code{font:.85em ui-monospace,SFMono-Regular,Menlo,monospace;background:#eff1f3;
padding:.1em .3em;border-radius:4px}
.ok{color:#1a7f37;font-weight:600}.ko{color:#cf222e;font-weight:600}.er{color:#9a6700}
p,li{max-width:52rem}
"""


def _inline(text: str) -> str:
    out = []
    for i, part in enumerate(re.split(r"(`[^`]*`)", text)):
        if i % 2:
            out.append(f"<code>{html.escape(part[1:-1])}</code>")
            continue
        part = html.escape(part)
        part = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", part)
        part = part.replace("✓", '<span class="ok">✓</span>')
        part = part.replace("✗", '<span class="ko">✗</span>')
        part = part.replace("⚠️", '<span class="er">⚠️</span>')
        out.append(part)
    return "".join(out)


def _cells(row: str) -> list[str]:
    row = row.strip()
    if row.startswith("|"):
        row = row[1:]
    if row.endswith("|"):
        row = row[:-1]
    # A pipe inside inline code is content, not a column break.
    cells, buf, in_code = [], "", False
    for ch in row:
        if ch == "`":
            in_code = not in_code
        if ch == "|" and not in_code:
            cells.append(buf.strip())
            buf = ""
            continue
        buf += ch
    cells.append(buf.strip())
    return cells


def render(markdown: str, title: str | None = None) -> str:
    """One HTML document for a report written by `report.build`."""
    lines = markdown.splitlines()
    body: list[str] = []
    para: list[str] = []
    i = 0

    def flush() -> None:
        if para:
            body.append(f"<p>{_inline(' '.join(para))}</p>")
            para.clear()

    while i < len(lines):
        line = lines[i]
        heading = re.match(r"^(#{1,3}) (.*)$", line)
        if heading:
            flush()
            level = len(heading.group(1))
            body.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
            title = title or heading.group(2)
        elif line.startswith("|"):
            flush()
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                rows.append(lines[i])
                i += 1
            head, rest = _cells(rows[0]), rows[2:] if len(rows) > 1 else []
            body.append("<table><thead><tr>")
            body.append("".join(f"<th>{_inline(c)}</th>" for c in head))
            body.append("</tr></thead><tbody>")
            for r in rest:
                body.append("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in _cells(r)) + "</tr>")
            body.append("</tbody></table>")
            continue
        elif line.startswith("- "):
            flush()
            body.append("<ul>")
            while i < len(lines) and lines[i].startswith("- "):
                body.append(f"<li>{_inline(lines[i][2:])}</li>")
                i += 1
            body.append("</ul>")
            continue
        elif not line.strip():
            flush()
        else:
            para.append(line.strip())
        i += 1
    flush()
    return (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        f"<title>{html.escape(title or 'HelioBench report')}</title>"
        f"<style>{_CSS}</style></head><body>\n" + "\n".join(body) + "\n</body></html>\n"
    )
