from __future__ import annotations
import re
from html.parser import HTMLParser
from core.logger import logger

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

    class FallbackTag:
        def __init__(self, name, attrs=None):
            self.name = name
            self.attrs = dict(attrs or [])
            self.children = []
            self.parent = None

        def get_text(self, separator=" ", strip=True):
            texts = []
            def _collect(node):
                if isinstance(node, str):
                    if node.strip():
                        texts.append(node)
                else:
                    for c in node.children:
                        _collect(c)
            _collect(self)
            joined = separator.join(texts)
            return joined.strip() if strip else joined

        def select(self, selector):
            results = []
            parts = [p.strip() for p in selector.split(",") if p.strip()]
            for part in parts:
                results.extend(self._select_single(part))
            seen = set()
            unique = []
            for r in results:
                if id(r) not in seen:
                    seen.add(id(r))
                    unique.append(r)
            return unique

        def _select_single(self, sel):
            tokens = sel.split()
            current_candidates = [self]
            for token in tokens:
                next_candidates = []
                for cand in current_candidates:
                    all_descendants = []
                    def _desc(n):
                        for c in n.children:
                            if isinstance(c, FallbackTag):
                                all_descendants.append(c)
                                _desc(c)
                    _desc(cand)
                    for d in all_descendants:
                        if self._matches(d, token):
                            next_candidates.append(d)
                current_candidates = next_candidates
            return current_candidates

        @staticmethod
        def _matches(node, token):
            if token.startswith("[") and token.endswith("]"):
                inside = token[1:-1]
                if "*=" in inside:
                    attr, val = inside.split("*=", 1)
                    val = val.strip("'\"")
                    return val in node.attrs.get(attr, "")
                elif "=" in inside:
                    attr, val = inside.split("=", 1)
                    val = val.strip("'\"")
                    return node.attrs.get(attr, "") == val
                else:
                    return inside in node.attrs
            
            classes = []
            tag_name = ""
            parts = re.split(r"(\.[a-zA-Z0-9_\-]+)", token)
            for p in parts:
                if not p:
                    continue
                if p.startswith("."):
                    classes.append(p[1:])
                else:
                    tag_name = p

            if tag_name and tag_name != "*" and node.name != tag_name:
                return False
            if classes:
                node_classes = node.attrs.get("class", "").split()
                for cls in classes:
                    if cls not in node_classes:
                        return False
            return True

        def select_one(self, selector):
            found = self.select(selector)
            return found[0] if found else None

        def decompose(self):
            self.children.clear()
            self.attrs.clear()
            if self.parent:
                try:
                    self.parent.children.remove(self)
                except Exception:
                    pass
                self.parent = None

    class FallbackParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.root = FallbackTag("document")
            self.current = self.root

        def handle_starttag(self, tag, attrs):
            node = FallbackTag(tag, attrs)
            node.parent = self.current
            self.current.children.append(node)
            self.current = node

        def handle_endtag(self, tag):
            if self.current.parent is not None:
                self.current = self.current.parent

        def handle_data(self, data):
            self.current.children.append(data)

    def BeautifulSoup(raw_html, parser="html.parser"):
        if isinstance(raw_html, bytes):
            raw_html = raw_html.decode("utf-8", errors="replace")
        p = FallbackParser()
        p.feed(raw_html)
        return p.root

try:
    import lxml
    HTML_PARSER_ENGINE = "lxml"
    HAS_LXML = True
    IS_C_ACCELERATED = True
except ImportError:
    HTML_PARSER_ENGINE = "html.parser"
    HAS_LXML = False
    IS_C_ACCELERATED = False
    # P0 Warning for Production Environments
    logger.warning(
        "⚠️ REPRODUCIBILITY ALERT: 'lxml' C-Engine is NOT installed. Falling back to native Python 'html.parser'. "
        "For guaranteed 100% reproducible DOM parsing and maximum CPU throughput in production, install lxml: pip install lxml"
    )

def create_soup(html_bytes: bytes) -> BeautifulSoup:
    return BeautifulSoup(html_bytes, HTML_PARSER_ENGINE)