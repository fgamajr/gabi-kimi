from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser
import re
from typing import Any


@dataclass(slots=True)
class HtmlTag:
    name: str
    attrs: dict[str, str]
    text_parts: list[str] = field(default_factory=list)
    order: int = 0

    @property
    def text(self) -> str:
        return re.sub(r"\s+", " ", " ".join(self.text_parts)).strip()


class FlatTagParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._stack: list[HtmlTag] = []
        self.tags: list[HtmlTag] = []
        self._counter = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._counter += 1
        self._stack.append(
            HtmlTag(name=tag.lower(), attrs={k: (v or "") for k, v in attrs}, order=self._counter)
        )

    def handle_data(self, data: str) -> None:
        if not data.strip():
            return
        for item in self._stack:
            item.text_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i].name == tag:
                finished = self._stack.pop(i)
                self.tags.append(finished)
                return


def parse_html_tags(html: str) -> list[HtmlTag]:
    p = FlatTagParser()
    p.feed(html)
    p.close()
    return sorted(p.tags, key=lambda t: t.order)


def select_tags(tags: list[HtmlTag], selector: str) -> list[HtmlTag]:
    selector = selector.strip()
    if not selector:
        return []

    # Comma union
    if "," in selector:
        out: list[HtmlTag] = []
        seen: set[tuple[int, str]] = set()
        for part in [x.strip() for x in selector.split(",") if x.strip()]:
            for t in select_tags(tags, part):
                key = (t.order, t.name)
                if key in seen:
                    continue
                seen.add(key)
                out.append(t)
        return sorted(out, key=lambda x: x.order)

    m = re.match(r"^(?P<tag>[a-zA-Z0-9*]+)(\[(?P<attr>[^\]=~*]+)\*='(?P<contains>[^']*)'\])?$", selector)
    if not m:
        # unsupported selector syntax for stdlib mode
        return []

    tag_name = m.group("tag").lower()
    attr = m.group("attr")
    contains = m.group("contains")

    out: list[HtmlTag] = []
    for t in tags:
        if tag_name != "*" and t.name != tag_name:
            continue
        if attr:
            value = t.attrs.get(attr, "")
            if contains and contains not in value:
                continue
        out.append(t)
    return out


def find_first_attr(tags: list[HtmlTag], attr: str) -> str | None:
    for t in tags:
        if attr in t.attrs and t.attrs[attr].strip():
            return t.attrs[attr].strip()
    return None
