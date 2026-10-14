"""robots.txt parser: UA groups, Allow/Disallow with longest-match precedence, * and $ wildcards."""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class Rule:
    allow: bool
    pattern: str
    line: str
    lineno: int


@dataclass
class Group:
    agents: list[str] = field(default_factory=list)
    rules: list[Rule] = field(default_factory=list)


def parse_robots(text: str) -> list[Group]:
    groups: list[Group] = []
    cur: Group | None = None
    last_was_agent = False
    for n, raw in enumerate((text or "").splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        k, v = line.split(":", 1)
        k, v = k.strip().lower(), v.strip()
        if k == "user-agent":
            if cur is None or not last_was_agent:
                cur = Group()
                groups.append(cur)
            cur.agents.append(v.lower())
            last_was_agent = True
        elif k in ("allow", "disallow"):
            last_was_agent = False
            if cur is None:
                continue
            cur.rules.append(Rule(allow=(k == "allow"), pattern=v, line=raw.strip(), lineno=n))
        else:
            last_was_agent = False
    return groups


def _match_len(pattern: str, path: str) -> int:
    """Return match length (specificity) or -1 if no match."""
    if pattern == "":
        return -1
    anchored = pattern.endswith("$")
    pat = pattern[:-1] if anchored else pattern
    regex = "".join(".*" if c == "*" else re.escape(c) for c in pat)
    m = re.match(regex + ("$" if anchored else ""), path)
    return len(pat) if m else -1


def select_group(groups: list[Group], ua: str) -> Group | None:
    """Most specific group: longest agent token contained in the UA; fall back to '*'."""
    ua_l = ua.lower()
    best, best_len = None, -1
    for g in groups:
        for a in g.agents:
            if a != "*" and a in ua_l and len(a) > best_len:
                best, best_len = g, len(a)
    if best:
        return best
    merged = [g for g in groups if "*" in g.agents]
    if not merged:
        return None
    if len(merged) == 1:
        return merged[0]
    combo = Group(agents=["*"])
    for g in merged:
        combo.rules.extend(g.rules)
    return combo


def check_access(groups: list[Group], ua: str, path: str) -> tuple[bool, Rule | None, str]:
    """(allowed, deciding_rule, group_label). Longest match wins; Allow wins ties."""
    g = select_group(groups, ua)
    if g is None:
        return True, None, "no matching group"
    label = ", ".join(g.agents)
    best: Rule | None = None
    best_len = -1
    for r in g.rules:
        ln = _match_len(r.pattern, path)
        if ln < 0:
            continue
        if ln > best_len or (ln == best_len and r.allow and best is not None and not best.allow):
            best, best_len = r, ln
    if best is None:
        return True, None, label
    return best.allow, best, label


def sitemaps(text: str) -> list[str]:
    return [m.group(1).strip() for m in re.finditer(r"(?im)^\s*sitemap\s*:\s*(\S+)", text or "")]
