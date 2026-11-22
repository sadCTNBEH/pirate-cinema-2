"""Network subset of ABP syntax used by the AdGuard Chromium filter lists."""

import re
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import urlsplit

TYPES = frozenset({
    "document", "subdocument", "script", "image", "stylesheet", "font", "object",
    "xmlhttprequest", "media", "ping", "websocket", "other",
})
ALIASES = {"xhr": "xmlhttprequest", "frame": "subdocument", "beacon": "ping", "css": "stylesheet"}
HOST = re.compile(r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
COSMETIC = re.compile(r"#(?:#|@?\?#|@?\$\$?#|@#|@?%#)")


def normalize_host(value: str) -> str:
    return value.rstrip(".").lower().encode("idna").decode("ascii")


def site_host(value: str) -> str:
    value = value.strip()
    try:
        url = urlsplit(value if "://" in value else "//" + value)
        host = normalize_host(url.hostname or "")
        if url.scheme not in ("", "http", "https") or not HOST.fullmatch(host):
            raise ValueError
        return host
    except (ValueError, UnicodeError):
        raise ValueError("Укажите домен или адрес сайта, например example.com.") from None


def on_domain(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def _site(host: str) -> str:
    # Common second level country namespaces, without an external suffix database.
    labels = host.split(".")
    if len(labels) > 2 and len(labels[-1]) == 2 and labels[-2] in {
        "ac", "co", "com", "edu", "gov", "net", "org",
    }:
        return ".".join(labels[-3:])
    if labels[-1].isdigit():
        return host
    return ".".join(labels[-2:])


@dataclass(frozen=True, slots=True)
class Conditions:
    important: bool
    include: frozenset[str]
    exclude: frozenset[str]
    domains: tuple[str, ...]
    excluded_domains: tuple[str, ...]
    third_party: bool | None

    def matches(self, host: str, kind: str, third_party: bool | None) -> bool:
        return (
            (not self.include or kind in self.include)
            and kind not in self.exclude
            and (self.third_party is None or self.third_party == third_party)
            and (not self.domains or any(on_domain(host, d) for d in self.domains))
            and not any(on_domain(host, d) for d in self.excluded_domains)
        )


@dataclass(frozen=True, slots=True)
class Rule:
    pattern: re.Pattern | str
    allow: bool
    conditions: Conditions

    def matches(self, url: str, lower: str, host: str, kind: str, third_party: bool | None) -> bool:
        return self.conditions.matches(host, kind, third_party) and (
            self.pattern in lower if isinstance(self.pattern, str) else self.pattern.search(url) is not None
        )


def _parts(line: str) -> tuple[str, tuple[str, ...]]:
    pattern, _, options = line.partition("$")
    return pattern, tuple(sorted(set(options.lower().split(",")) - {""}))


@lru_cache(maxsize=4096)
def _conditions(options: tuple[str, ...]) -> Conditions | None:
    include: set[str] = set()
    exclude: set[str] = set()
    domains: list[str] = []
    excluded_domains: list[str] = []
    third_party = None
    for option in options:
        name = option.removeprefix("~")
        kind = ALIASES.get(name, name)
        if kind in TYPES:
            (exclude if option.startswith("~") else include).add(kind)
        elif option.startswith("domain="):
            for item in option[7:].split("|"):
                domain = normalize_host(item.removeprefix("~"))
                if not HOST.fullmatch(domain):
                    return None
                (excluded_domains if item.startswith("~") else domains).append(domain)
        elif option in {"third-party", "~third-party", "3p", "first-party", "~first-party", "1p"}:
            third_party = option in {"third-party", "3p", "~first-party"}
        elif option not in {"match-case", "important"}:
            return None
    return Conditions("important" in options, frozenset(include), frozenset(exclude),
                      tuple(domains), tuple(excluded_domains), third_party)


def _parse(pattern: str, options: tuple[str, ...]) -> tuple[str, Rule] | None:
    allow = pattern.startswith("@@")
    if allow:
        pattern = pattern[2:]
    # Skip arbitrary regexes and unsupported transforms rather than turning
    # them into broader blocking rules.
    if not pattern or (pattern.startswith("/") and pattern.endswith("/")) or pattern.count("*") > 3:
        return None
    conditions = _conditions(options)
    if conditions is None:
        return None
    domain_anchor = pattern.startswith("||")
    start_anchor = pattern.startswith("|")
    end_anchor = pattern.endswith("|")
    core = pattern[2 if domain_anchor else int(start_anchor):len(pattern) - int(end_anchor)]
    if domain_anchor and (not core or not core[0].isalnum()):
        return None
    literals = re.split(r"[*^]", core)
    longest = max((literal.removeprefix("https://").removeprefix("http://")
                   for literal in literals), key=len)
    # Every candidate must contain this literal. Short rules share a small
    # fallback bucket; common long rules avoid a full scan on every request.
    key = longest.lower()[:7] if len(longest) >= 7 else longest.lower()[:3] if len(longest) >= 3 else ""
    if not key and not longest and not conditions.domains:
        return None
    if not (start_anchor or end_anchor or len(literals) > 1 or "match-case" in options):
        return key, Rule(core.lower(), allow, conditions)
    prefix = r"^(?:https?|wss?)://(?:[^./:?#@]+\.)*" if domain_anchor else ("^" if start_anchor else "")
    body = r"(?:[^a-zA-Z0-9_.%\-]|$)".join(
        ".*".join(map(re.escape, fragment.split("*"))) for fragment in core.split("^")
    )
    regex = re.compile(prefix + body + ("$" if end_anchor else ""), 0 if "match-case" in options else re.ASCII | re.I)
    return key, Rule(regex, allow, conditions)


class NetworkRules:
    def __init__(self, lists: list[str]):
        self.index: dict[str, list[Rule]] = defaultdict(list)
        self.document_exceptions: dict[str, list[Rule]] = defaultdict(list)
        self.blocked_hosts: set[str] = set()
        def entries():
            for source in lists:
                for raw in source.splitlines():
                    line = raw.strip()
                    if line and len(line) <= 512 and not line.startswith(("!", "[", "#")) and not COSMETIC.search(line):
                        yield _parts(line)

        disabled = {
            (pattern, tuple(o for o in options if o != "badfilter"))
            for pattern, options in entries() if "badfilter" in options
        }
        self.count = 0
        for pattern, options in entries():
            if "badfilter" in options or (pattern, options) in disabled:
                continue
            if not options and pattern.startswith("||") and pattern.endswith("^"):
                host = pattern[2:-1].lower()
                if HOST.fullmatch(host):
                    self.blocked_hosts.add(host)
                    self.count += 1
                    continue
            try:
                parsed = _parse(pattern, options)
            except (ValueError, re.error):
                continue
            if parsed is not None:
                key, rule = parsed
                self.index[key].append(rule)
                if rule.allow and "document" in rule.conditions.include:
                    self.document_exceptions[key].append(rule)
                self.count += 1

    @staticmethod
    def _candidates(index: dict[str, list[Rule]], lower: str):
        yield from index.get("", ())
        for size in (3, 7):
            for key in {lower[i:i + size] for i in range(len(lower) - size + 1)}:
                yield from index.get(key, ())

    def blocks(self, url: str, source_url: str, kind: str) -> bool:
        target, source = urlsplit(url), urlsplit(source_url)
        host, origin = (target.hostname or "").rstrip("."), (source.hostname or "").rstrip(".")
        if "@" in target.netloc:
            url = target._replace(netloc=target.netloc.rsplit("@", 1)[-1]).geturl()
        third_party = _site(host) != _site(origin) if origin else None
        labels = host.split(".")
        blocked = any(".".join(labels[i:]) in self.blocked_hosts for i in range(len(labels)))
        allowed = important_block = important_allow = False
        lower = url.lower()
        for rule in self._candidates(self.index, lower):
            if rule.matches(url, lower, origin, kind, third_party):
                if rule.allow:
                    allowed = True
                    important_allow |= rule.conditions.important
                elif rule.conditions.important:
                    important_block = True
                else:
                    blocked = True
        if important_block:
            return not important_allow
        if not blocked or allowed:
            return False
        source_lower = source_url.lower()
        return not any(
            rule.matches(source_url, source_lower, origin, "document", False)
            for rule in self._candidates(self.document_exceptions, source_lower)
        )
