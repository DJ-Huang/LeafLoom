"""Render the authored, multilingual help center into the public static website."""
from __future__ import annotations

from collections import Counter
from html import escape
import json
from pathlib import Path
import re
import shutil
from urllib.parse import quote, unquote, urlsplit

from markdown_it import MarkdownIt

ROOT = Path(__file__).resolve().parents[1]
LANGUAGES = ("en", "zh-CN", "ja")
REPOSITORY = "https://github.com/DJ-Huang/LeafLoom/blob/main/"
SECTIONS = ("goal", "before", "steps", "result", "troubleshooting", "next")


def heading_id(text: str) -> str:
    # Match the heading links used in the repository's existing Markdown guides.
    return re.sub(r"[^\w\- ]", "", text.lower()).replace(" ", "-")


def safe_url(value: str) -> None:
    parsed = urlsplit(value)
    if (re.search(r"[\x00-\x20\\]", value) or value.startswith("//")
            or parsed.scheme not in ("", "http", "https", "mailto")):
        raise ValueError(f"Unsafe documentation URL: {value}")


class Documentation:
    def __init__(self, base_url: str, root: Path = ROOT):
        self.root = root.resolve()
        self.base_url = base_url.rstrip("/") + "/"
        self.base = urlsplit(self.base_url).path
        self.navigation = json.loads((self.root / "docs/help/navigation.json").read_text(encoding="utf-8"))
        self.slugs = [slug for group in self.navigation["groups"] for slug in group["articles"]]
        if len(set(self.slugs)) != len(self.slugs) or any(not re.fullmatch(r"[a-z0-9-]+", slug) for slug in self.slugs):
            raise ValueError("Documentation slugs must be unique and URL-safe")
        self.sources = {}
        for lang in LANGUAGES:
            for slug in self.slugs:
                name = self.navigation.get("sources", {}).get(slug, "docs/{lang}/help/{slug}.md")
                if isinstance(name, dict):
                    name = name[lang]
                path = (self.root / name.format(lang=lang, slug=slug)).resolve()
                if not path.is_relative_to(self.root) or not path.is_file():
                    raise ValueError(f"Missing or invalid {lang} article: {slug}")
                self.sources[path] = (lang, slug)
        self.media: set[Path] = set()
        self.articles = {}

    def route(self, lang: str, slug: str = "") -> str:
        return f"{self.base}docs/{lang}/" + (f"{slug}/" if slug else "")

    def resolve_link(self, value: str, source: Path, image: bool = False) -> str:
        safe_url(value)
        parsed = urlsplit(value)
        if parsed.scheme:
            if image:
                raise ValueError("Documentation images must be public repository assets")
            return value
        if not parsed.path:
            return value
        if parsed.path.startswith("/") or parsed.query:
            raise ValueError(f"Use repository-relative documentation paths: {value}")
        target = (source.parent / unquote(parsed.path)).resolve()
        if not target.is_relative_to(self.root) or not target.is_file():
            raise ValueError(f"Broken documentation link in {source}: {value}")
        relative = target.relative_to(self.root).as_posix()
        fragment = "#" + quote(unquote(parsed.fragment), safe="-_") if parsed.fragment else ""
        if image:
            if not relative.startswith(("assets/screenshots/", "assets/brand/", "docs/assets/")) or target.suffix.lower() not in (".svg", ".png", ".jpg", ".jpeg", ".webp", ".gif"):
                raise ValueError(f"Not a public documentation image: {value}")
            self.media.add(target)
            return self.base + "docs/media/" + quote(relative)
        if target in self.sources:
            return self.route(*self.sources[target]) + fragment
        if relative == "docs/README.md":
            return self.route(self.sources[source][0]) + fragment
        if not parsed.fragment and relative in ("README.md", "docs/zh-CN/README.md", "docs/ja/README.md"):
            lang = "en" if relative == "README.md" else relative.split("/")[1]
            return self.base + ("" if lang == "en" else lang + "/") + fragment
        return REPOSITORY + quote(relative) + fragment

    def read_article(self, source: Path) -> dict:
        lang, slug = self.sources[source]
        markdown = source.read_text(encoding="utf-8")
        parser = MarkdownIt("commonmark", {"html": False}).enable("table")
        tokens = parser.parse(markdown)
        toc = []
        ids = Counter()
        structured = source.parent.name == "help"
        section = 0
        title = ""
        plain = []
        summary = ""
        for index, token in enumerate(tokens):
            if token.type == "inline":
                text = "".join(child.content for child in token.children or [] if child.type not in ("image", "html_inline"))
                plain.append(text)
                if not summary and index and tokens[index - 1].type == "paragraph_open" and not re.match(r"^(English|中文|日本語)\s*[·|]", text):
                    summary = text
                for child in token.children or []:
                    if child.type == "link_open":
                        child.attrSet("href", self.resolve_link(child.attrGet("href") or "", source))
                    elif child.type == "image":
                        child.attrSet("src", self.resolve_link(child.attrGet("src") or "", source, image=True))
                        child.attrSet("loading", "lazy")
            elif token.type in ("fence", "code_block"):
                plain.append(token.content)
            if token.type != "heading_open":
                continue
            inline = tokens[index + 1]
            text = "".join(child.content for child in inline.children or [] if child.type in ("text", "code_inline"))
            if token.tag == "h1":
                if title:
                    raise ValueError(f"Multiple article titles: {source}")
                title = text
            if structured and token.tag == "h2":
                if section >= len(SECTIONS):
                    raise ValueError(f"Expected six guide sections: {source}")
                anchor = SECTIONS[section]
                section += 1
            else:
                anchor = heading_id(text) or "section"
            count = ids[anchor]
            ids[anchor] += 1
            anchor += f"-{count}" if count else ""
            token.attrSet("id", anchor)
            if token.tag == "h2":
                toc.append({"id": anchor, "text": text})
        if not title or (structured and section != 6):
            raise ValueError(f"Missing title or six guide sections: {source}")

        default_image = parser.renderer.rules["image"]

        def image(tokens, index, options, env):
            token = tokens[index]
            return f'<a class="article-image" data-zoom href="{escape(token.attrGet("src") or "", quote=True)}">{default_image(tokens, index, options, env)}</a>'

        parser.renderer.rules["image"] = image
        parser.renderer.rules["table_open"] = lambda *_: '<div class="table-scroll" tabindex="0"><table>\n'
        parser.renderer.rules["table_close"] = lambda *_: '</table></div>\n'
        html = parser.renderer.render(tokens, parser.options, {})
        return {"slug": slug, "lang": lang, "title": title, "summary": summary,
                "toc": toc, "html": html, "text": " ".join(plain), "ids": set(ids), "source": source}

    def build(self, output: Path) -> list[str]:
        self.articles = {key: self.read_article(source) for source, key in self.sources.items()}
        target = output / "docs"
        target.mkdir(parents=True, exist_ok=True)
        for name in ("help.css", "help.js"):
            shutil.copy2(self.root / "site/help" / name, target / name)
        template = (self.root / "site/help/page.html").read_text(encoding="utf-8")
        version = json.loads((self.root / "desktop/package.json").read_text(encoding="utf-8"))["version"]
        urls = []
        for lang in LANGUAGES:
            catalog = json.loads((self.root / f"vault_rag/locales/{lang}.json").read_text(encoding="utf-8"))
            labels = {key.removeprefix("site.help_"): value for key, value in catalog.items() if key.startswith("site.help_")}

            def t(key):
                value = labels[key]
                if not value.strip():
                    raise ValueError(f"Missing {lang} help translation: {key}")
                return escape(value, quote=True)

            articles = {slug: self.articles[lang, slug] for slug in self.slugs}
            search = f'''<form class="search" role="search" hidden><label class="sr-only" for="help-search">{t("search")}</label><span aria-hidden="true">⌕</span><input id="help-search" type="search" placeholder="{t("placeholder")}" autocomplete="off" maxlength="160" aria-controls="search-results"><kbd aria-hidden="true">⌘ K</kbd><button type="reset" aria-label="{t("clear")}">×</button></form><div id="search-results" class="search-results" aria-live="polite" hidden></div><noscript><p class="muted">{t("no_js")}</p></noscript>'''
            for slug in ["", *self.slugs]:
                article = articles.get(slug)
                group = next((group for group in self.navigation["groups"] if slug in group["articles"]), None)
                navigation = "".join(
                    f'<details{" open" if not article or item == group else ""}><summary>{t("group_" + item["id"])}</summary>' +
                    "".join(f'<a href="{self.route(lang, name)}"' + (' aria-current="page"' if name == slug else '') + f'>{escape(articles[name]["title"])}</a>' for name in item["articles"]) + '</details>'
                    for item in self.navigation["groups"])
                title = (article["title"] + " · " if article else "LeafLoom · ") + labels["home"]
                description = article["summary"] if article else labels["intro"]
                if article:
                    index = self.slugs.index(slug)
                    previous = self.slugs[index - 1] if index else None
                    following = self.slugs[index + 1] if index + 1 < len(self.slugs) else None
                    adjacent = "".join(f'<a href="{self.route(lang, name)}"><small>{t(label)}</small>{escape(articles[name]["title"])} <span aria-hidden="true">→</span></a>' if name else '<span></span>' for name, label in ((previous, "previous"), (following, "next")))
                    body = f'''{search}<nav class="breadcrumbs" aria-label="{t("breadcrumbs")}"><a href="{self.route(lang)}">{t("home")}</a><span>/</span><a href="{self.route(lang)}#{group["id"]}">{t("group_" + group["id"])}</a></nav><p class="article-meta">{t("version")} {escape(version)} · {t("local_first")}</p><div class="reading-layout"><article class="prose">{article["html"]}<nav class="adjacent" aria-label="{t("adjacent")}">{adjacent}</nav><a class="source-link" href="{REPOSITORY + article["source"].relative_to(self.root).as_posix()}">{t("source")} ↗</a></article><aside class="toc" aria-label="{t("contents")}"><strong>{t("contents")}</strong>{"".join(f'<a href="#{item["id"]}">{escape(item["text"])}</a>' for item in article["toc"])}</aside></div>'''
                else:
                    starters = (("first-vault", "start"), ("workspace", "features"), ("faq", "problems"))
                    cards = "".join(f'<a href="{self.route(lang, name)}"><small>0{index}</small><strong>{t(label)}</strong><span>{escape(articles[name]["title"])} →</span></a>' for index, (name, label) in enumerate(starters, 1))
                    groups = "".join(f'<section class="topic-group" id="{item["id"]}"><div class="group-title"><h2>{t("group_" + item["id"])}</h2><span>{len(item["articles"])} {t("count")}</span></div><div class="topics">' + "".join(f'<a href="{self.route(lang, name)}">{escape(articles[name]["title"])}<span aria-hidden="true">↗</span></a>' for name in item["articles"]) + '</div></section>' for item in self.navigation["groups"])
                    body = f'<section class="welcome"><p class="eyebrow">LEAFLOOM / {t("home")}</p><h1>{t("tagline")}</h1><p>{t("intro")}</p>{search}<div class="entrypoints">{cards}</div></section><div class="catalog-title"><h2>{t("browse")}</h2><span>{len(articles)} {t("count")}</span></div>{groups}'
                values = {
                    **{key: escape(value, quote=True) for key, value in labels.items()},
                    "lang": lang, "base": escape(self.base), "docs_home": self.route(lang),
                    "website_url": self.base + ("" if lang == "en" else lang + "/"),
                    "title": escape(title), "description": escape(description), "body": body, "topics": navigation,
                    "canonical": escape(self.base_url + f"docs/{lang}/" + (slug + "/" if slug else "")),
                    "alternates": "".join(f'<link rel="alternate" hreflang="{other}" href="{self.base_url}docs/{other}/' + (slug + '/' if slug else '') + '">' for other in LANGUAGES),
                    "language_links": "".join(f'<a href="{self.route(other, slug)}" lang="{other}" hreflang="{other}" data-language' + (' aria-current="page"' if other == lang else '') + f'>{label}</a>' for other, label in (("en", "English"), ("zh-CN", "中文"), ("ja", "日本語"))),
                }
                html = re.sub(r"\{\{(\w+)\}\}", lambda match: values[match[1]], template)
                folder = target / lang / slug
                folder.mkdir(parents=True, exist_ok=True)
                (folder / "index.html").write_text(html, encoding="utf-8")
                urls.append(self.base_url + f"docs/{lang}/" + (slug + "/" if slug else ""))
            index = {"messages": labels, "articles": [{key: article[key] for key in ("slug", "title", "summary", "text")} | {"url": self.route(lang, article["slug"])} for article in articles.values()]}
            (target / lang / "search.json").write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
        for source in self.media:
            destination = target / "media" / source.relative_to(self.root)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        (target / "index.html").write_text(f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta http-equiv="refresh" content="0;url={self.route("en")}"><title>LeafLoom documentation</title></head><body>' + " ".join(f'<a href="{self.route(lang)}">{label}</a>' for lang, label in (("en", "English"), ("zh-CN", "中文"), ("ja", "日本語"))) + '</body></html>', encoding="utf-8")
        return urls
