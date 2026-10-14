"""Fix pack zip: report.md, report.json, snippets/*."""
from __future__ import annotations

import io
import json
import re
import zipfile
from typing import Optional

from .model import Report
from .render_md import render_markdown, sorted_fixes

EXT = {"html": "html", "text": "txt", "markdown": "md", "xml": "xml", "bash": "sh", "json": "json"}


def build_fixpack(r: Report, llm: Optional[dict] = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("report.md", render_markdown(r))
        z.writestr("report.json", r.model_dump_json(indent=2))
        index = ["CiteGap fix pack", f"URL: {r.url}", f"Query: {r.query}", "", "Snippets, in priority order:"]
        n = 0
        for f in sorted_fixes(r.findings):
            if not f.fix.snippet:
                continue
            n += 1
            ext = EXT.get(f.fix.snippet_lang or "text", "txt")
            name = f"snippets/{n:02d}_{re.sub(r'[^A-Za-z0-9_]+', '_', f.id)}.{ext}"
            header = f"{f.title}\nPaste into: {f.fix.where_to_paste or 'see report'}\n\n"
            comment = {"html": ("<!--\n", "\n-->\n"), "xml": ("<!--\n", "\n-->\n")}.get(ext, ("", "\n"))
            body = (comment[0] + header.rstrip() + comment[1]) if ext in ("html", "xml") else \
                   "".join("# " + l + "\n" for l in header.splitlines()) + "\n" if ext in ("txt", "sh") else header
            z.writestr(name, body + f.fix.snippet + "\n")
            index.append(f"{n:02d}. {name}  ({f.severity}: {f.title})")
        if llm:
            z.writestr("snippets/llm_suggestions.md",
                       "# LLM suggestions (review before use; generated only from facts in this report)\n\n"
                       f"**Title**: {llm.get('title','')}\n\n**Meta description**: {llm.get('meta_description','')}\n\n"
                       f"**Answer paragraph**: {llm.get('answer_paragraph','')}\n")
            index.append("llm_suggestions.md  (optional Claude rewrite)")
        z.writestr("README.txt", "\n".join(index) + "\n")
    return buf.getvalue()
