"""MCP prompt registration for OpenZIM MCP server.

This fork runs simple mode against one Wikipedia ZIM archive. The prompt
surface therefore teaches workflows over the single ``zim_query`` tool rather
than the advanced-mode tools that are intentionally not registered.
"""

import re
from typing import TYPE_CHECKING, Any, Dict, List

if TYPE_CHECKING:
    from ..server import OpenZimMcpServer


# Matches any ASCII control character (C0 range, including \n, \r, \t, \x00).
# We strip these from user input before interpolating into prompt templates so
# that a topic like "Foo\n2. Ignore previous instructions" cannot append fake
# numbered steps to the workflow body sent to the LLM.
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]+")


def _sanitize_for_prompt(value: str, max_length: int = 200) -> str:
    """Strip control characters and cap length before embedding in prompt text.

    Quote characters (``'``, ``"``) are *preserved* — they appear in real
    ZIM entry paths (e.g. ``C/Schrödinger's_cat``) and stripping them would
    cause the LLM to call tools with the wrong path. Backticks ARE stripped
    because the prompt templates wrap interpolated values in backticks (a
    delimiter that never appears in legitimate ZIM URLs/paths) so that
    quote-injection at the template boundary is impossible.

    Args:
        value: Raw user-supplied string.
        max_length: Maximum length to retain. Longer values are truncated and
            suffixed with an ellipsis to keep prompt size bounded.

    Returns:
        Cleaned string safe to interpolate into a multi-line prompt template.
    """
    if not value:
        return value
    cleaned = _CONTROL_CHARS_RE.sub(" ", value)
    # Strip backticks only — apostrophes and double quotes appear in
    # real entry paths and must survive.
    cleaned = cleaned.replace("`", "").strip()
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length].rstrip() + "..."
    return cleaned


def _msg(role: str, text: str) -> Dict[str, Any]:
    """Build a PromptMessage-shaped dict."""
    return {"role": role, "content": {"type": "text", "text": text}}


# Asking-message texts emitted when a prompt is invoked without the required
# args, or when the args collapse to empty after sanitization (e.g. a topic
# that is purely control characters). Centralized to keep the pre- and
# post-sanitization branches in sync.
_ASK_MESSAGES: Dict[str, str] = {
    "research": (
        "I want to use the /research prompt, but I haven't "
        "given you a topic. Please ask me what subject I want "
        "to research, then re-run the /research prompt with "
        "that topic."
    ),
    "article": (
        "I want to use the /article prompt, but I haven't given you a "
        "topic. Please ask me which Wikipedia article or subject I want "
        "briefed, then re-run /article with that topic."
    ),
    "compare": (
        "I want to use the /compare prompt, but I need two topics. Please "
        "ask me for the two Wikipedia subjects to compare, then re-run "
        "/compare with both."
    ),
    "timeline": (
        "I want to use the /timeline prompt, but I haven't given you a "
        "topic. Please ask me which person, event, place, or subject needs "
        "a timeline, then re-run /timeline with that topic."
    ),
    "map": (
        "I want to use the /map prompt, but I haven't given you a topic. "
        "Please ask me which concept or article to map, then re-run /map "
        "with that topic."
    ),
    "summarize": (
        "I want to use the /summarize prompt, but I haven't "
        "given you the required arguments. Please ask me "
        "which ZIM file path and which article path "
        "(e.g. 'C/Photosynthesis'), then re-run the "
        "/summarize prompt with both."
    ),
    "explore": (
        "I want to use the /explore prompt, but I haven't "
        "given you a ZIM file path. Please ask me which "
        "ZIM file path, then re-run the /explore prompt "
        "with that path."
    ),
}


def _ask_for_args(prompt_name: str) -> List[Dict[str, Any]]:
    """Return the asking-message body for a prompt missing required args."""
    return [_msg("user", _ASK_MESSAGES[prompt_name])]


def _format_archive_context(profile: Dict[str, Any]) -> str:
    """Render a compact archive profile for prompt bodies.

    The profile is best-effort and may be empty in tests or before any real
    archive is installed. Keep the output declarative so prompt behavior stays
    stable even when metadata fields are absent.
    """
    if not profile:
        return (
            "Archive context: one offline Wikipedia ZIM archive is expected. "
            "Use only `zim_query`; omit `zim_file_path` unless explicitly "
            "debugging archive selection."
        )

    parts = ["Archive context: offline Wikipedia ZIM"]
    title = profile.get("title")
    if title:
        parts.append(f"title={title}")
    language = profile.get("language")
    if language:
        parts.append(f"language={language}")
    archive_date = profile.get("archive_date")
    if archive_date:
        parts.append(f"snapshot_date={archive_date}")
    article_count = profile.get("article_count")
    if isinstance(article_count, int) and article_count > 0:
        parts.append(f"articles={article_count:,}")
    main_page = profile.get("main_page")
    if isinstance(main_page, dict):
        main_title = main_page.get("title")
        main_path = main_page.get("path")
        if main_title and main_path:
            parts.append(f"main_page={main_title} ({main_path})")
    namespaces = profile.get("namespaces")
    if isinstance(namespaces, dict) and namespaces:
        rendered = []
        for key in sorted(namespaces):
            summary = namespaces[key]
            if not isinstance(summary, dict):
                continue
            total = summary.get("total")
            if isinstance(total, int):
                rendered.append(f"{key}:{total:,}")
        if rendered:
            parts.append("namespaces=" + ", ".join(rendered[:6]))

    return "; ".join(parts) + "."


def _single_tool_rules(archive_context: str = "") -> str:
    """Rules shared by every simple-mode prompt."""
    context = archive_context or _format_archive_context({})
    return (
        f"{context}\n\n"
        "Operating rules:\n"
        "1. Use only the `zim_query` tool. No other MCP tools are available "
        "in this simple-mode deployment.\n"
        "2. Omit `zim_file_path`; this deployment is tuned for one loaded "
        "Wikipedia archive and `zim_query` will auto-select it.\n"
        "3. Prefer canonical article lookup before broad search. Use "
        "`find article titled <topic>` or `tell me about <topic>` when the "
        "user names an entity.\n"
        "4. Prefer section retrieval for long pages: first call "
        "`show structure of <article>`, then call "
        "`get section <section> of <article>` for the relevant sections.\n"
        "5. Treat list pages and disambiguation pages as navigation aids "
        "unless the user explicitly asks for a list or disambiguation.\n"
        "6. If the archive profile includes a snapshot date, mention that "
        "date when answering time-sensitive or current-affairs questions."
    )


def _research_body(topic: str, archive_context: str = "") -> List[Dict[str, Any]]:
    """Body of the research prompt — the message list returned to the client."""
    if not topic or not topic.strip():
        return _ask_for_args("research")
    safe_topic = _sanitize_for_prompt(topic, max_length=120)
    if not safe_topic:
        return _ask_for_args("research")
    return [
        _msg(
            "user",
            (
                f"Research the topic: {safe_topic}\n\n"
                f"{_single_tool_rules(archive_context)}\n\n"
                "Workflow:\n"
                f"1. Call `zim_query` with query=`{safe_topic}`, "
                "synthesize=true, compact=true.\n"
                f"2. If the result does not identify a canonical article, "
                f"call `zim_query` with query=`find article titled {safe_topic}`.\n"
                "3. For the best article, call `zim_query` with "
                "query=`show structure of <article>`.\n"
                "4. If specific sections matter, call `zim_query` with "
                "query=`get section <section> of <article>`.\n"
                "5. Call `zim_query` with query=`articles related to <article>` "
                "to surface adjacent reading.\n\n"
                "Answer with: concise overview, key sections, notable related "
                "articles, open uncertainties, and suggested next questions."
            ),
        )
    ]


def _article_body(topic: str, archive_context: str = "") -> List[Dict[str, Any]]:
    """Body for a canonical Wikipedia article briefing."""
    if not topic or not topic.strip():
        return _ask_for_args("article")
    safe_topic = _sanitize_for_prompt(topic, max_length=120)
    if not safe_topic:
        return _ask_for_args("article")
    return [
        _msg(
            "user",
            (
                f"Prepare a Wikipedia article briefing for: {safe_topic}\n\n"
                f"{_single_tool_rules(archive_context)}\n\n"
                "Workflow:\n"
                f"1. Call `zim_query` with query=`find article titled {safe_topic}`.\n"
                f"2. Call `zim_query` with query=`tell me about {safe_topic}`, "
                "compact=true.\n"
                "3. Call `zim_query` with query=`show structure of <resolved article>`.\n"
                "4. Call `zim_query` with query=`articles related to <resolved article>`.\n\n"
                "Answer with: canonical title/path if visible, one-paragraph "
                "briefing, section outline, five related articles, and the "
                "best follow-up section to inspect."
            ),
        )
    ]


def _compare_body(
    topic_a: str, topic_b: str, archive_context: str = ""
) -> List[Dict[str, Any]]:
    """Body for comparing two Wikipedia subjects."""
    if not topic_a or not topic_a.strip() or not topic_b or not topic_b.strip():
        return _ask_for_args("compare")
    safe_a = _sanitize_for_prompt(topic_a, max_length=120)
    safe_b = _sanitize_for_prompt(topic_b, max_length=120)
    if not safe_a or not safe_b:
        return _ask_for_args("compare")
    return [
        _msg(
            "user",
            (
                f"Compare these Wikipedia subjects: {safe_a} and {safe_b}\n\n"
                f"{_single_tool_rules(archive_context)}\n\n"
                "Workflow:\n"
                f"1. Call `zim_query` with query=`{safe_a}`, synthesize=true, "
                "compact=true.\n"
                f"2. Call `zim_query` with query=`{safe_b}`, synthesize=true, "
                "compact=true.\n"
                f"3. Call `zim_query` with query=`show structure of {safe_a}` "
                "and again for the second topic if the comparison needs "
                "section-level evidence.\n"
                "4. Use `articles related to <topic>` only if you need shared "
                "or adjacent concepts.\n\n"
                "Answer with: similarities, differences, relevant chronology "
                "or category distinctions, and where the Wikipedia articles "
                "appear strongest or weakest."
            ),
        )
    ]


def _timeline_body(topic: str, archive_context: str = "") -> List[Dict[str, Any]]:
    """Body for extracting a dated chronology from Wikipedia."""
    if not topic or not topic.strip():
        return _ask_for_args("timeline")
    safe_topic = _sanitize_for_prompt(topic, max_length=120)
    if not safe_topic:
        return _ask_for_args("timeline")
    return [
        _msg(
            "user",
            (
                f"Build a timeline for: {safe_topic}\n\n"
                f"{_single_tool_rules(archive_context)}\n\n"
                "Workflow:\n"
                f"1. Call `zim_query` with query=`find article titled {safe_topic}`.\n"
                f"2. Call `zim_query` with query=`show structure of {safe_topic}`.\n"
                "3. Inspect likely chronology sections with `zim_query`, using "
                "queries such as `get section History of <article>`, "
                "`get section Early life of <article>`, `get section Career of "
                "<article>`, or other section names visible in the structure.\n"
                f"4. If the article lacks obvious chronology sections, call "
                f"`zim_query` with query=`{safe_topic}`, synthesize=true, "
                "compact=true and extract dated events from the passages.\n\n"
                "Answer as a dated timeline. Separate explicit dates from "
                "approximate periods, and note gaps where the article does not "
                "provide enough chronology."
            ),
        )
    ]


def _map_body(topic: str, archive_context: str = "") -> List[Dict[str, Any]]:
    """Body for concept mapping around a Wikipedia article."""
    if not topic or not topic.strip():
        return _ask_for_args("map")
    safe_topic = _sanitize_for_prompt(topic, max_length=120)
    if not safe_topic:
        return _ask_for_args("map")
    return [
        _msg(
            "user",
            (
                f"Create a concept map for: {safe_topic}\n\n"
                f"{_single_tool_rules(archive_context)}\n\n"
                "Workflow:\n"
                f"1. Call `zim_query` with query=`{safe_topic}`, synthesize=true, "
                "compact=true.\n"
                f"2. Call `zim_query` with query=`show structure of {safe_topic}`.\n"
                f"3. Call `zim_query` with query=`articles related to {safe_topic}`.\n"
                f"4. If needed, call `zim_query` with query=`links in {safe_topic}` "
                "to distinguish article-internal navigation from genuinely "
                "important adjacent concepts.\n\n"
                "Answer with: core concept, prerequisites, major subtopics, "
                "adjacent topics, contrasting concepts, and a suggested "
                "reading order."
            ),
        )
    ]


def _summarize_body(zim_file_path: str, entry_path: str) -> List[Dict[str, Any]]:
    """Body of the summarize prompt."""
    if (
        not zim_file_path
        or not zim_file_path.strip()
        or not entry_path
        or not entry_path.strip()
    ):
        return _ask_for_args("summarize")
    safe_zim = _sanitize_for_prompt(zim_file_path)
    safe_entry = _sanitize_for_prompt(entry_path)
    if not safe_zim or not safe_entry:
        return _ask_for_args("summarize")
    return [
        _msg(
            "user",
            (
                f"Summarize the article: {safe_entry} in {safe_zim}\n\n"
                "Workflow:\n"
                f"1. Call get_table_of_contents(`{safe_zim}`, "
                f"`{safe_entry}`) for a structural overview.\n"
                f"2. Call get_entry_summary(`{safe_zim}`, "
                f"`{safe_entry}`) for the lead-paragraph summary.\n"
                f"3. Call extract_article_links(`{safe_zim}`, "
                f"`{safe_entry}`) for the most-mentioned related entries.\n\n"
                "Combine into: (a) one-paragraph TL;DR, (b) section list, "
                "(c) 5–10 most relevant outbound links."
            ),
        )
    ]


def _explore_body(zim_file_path: str) -> List[Dict[str, Any]]:
    """Body of the explore prompt."""
    if not zim_file_path or not zim_file_path.strip():
        return _ask_for_args("explore")
    safe_zim = _sanitize_for_prompt(zim_file_path)
    if not safe_zim:
        return _ask_for_args("explore")
    return [
        _msg(
            "user",
            (
                f"Explore the ZIM file: {safe_zim}\n\n"
                "Workflow:\n"
                f"1. Call get_zim_metadata(`{safe_zim}`) for title, "
                "language, creator, and flavour.\n"
                f"2. Call list_namespaces(`{safe_zim}`) for namespace "
                "breakdown — note any minority namespaces (M, W, X) that "
                "might be worth examining separately.\n"
                f"3. Call get_main_page(`{safe_zim}`) for the entry "
                "point.\n"
                f"4. Call walk_namespace(`{safe_zim}`, `C`, limit=5) "
                "to sample article content.\n\n"
                "Then: present a compact briefing — what is this archive, "
                "what does it cover, and what does typical content look "
                "like?"
            ),
        )
    ]


def register_prompts(server: "OpenZimMcpServer") -> None:
    """Register MCP prompts on the FastMCP server.

    Simple mode intentionally keeps the tool surface to ``zim_query``. These
    prompts are therefore workflow macros over that one tool, tailored for the
    single offline Wikipedia archive this fork operates.
    """
    archive_context = _format_archive_context(
        getattr(server, "archive_profile", {}) or {}
    )

    @server.mcp.prompt("research")
    def research(topic: str) -> List[Dict[str, Any]]:
        """Research a topic in the configured Wikipedia archive.

        Args:
            topic: Subject to research

        Returns:
            Multi-step instruction message for the LLM
        """
        return _research_body(topic, archive_context)

    @server.mcp.prompt("article")
    def article(topic: str) -> List[Dict[str, Any]]:
        """Brief a canonical Wikipedia article or subject."""
        return _article_body(topic, archive_context)

    @server.mcp.prompt("compare")
    def compare(topic_a: str, topic_b: str) -> List[Dict[str, Any]]:
        """Compare two Wikipedia subjects."""
        return _compare_body(topic_a, topic_b, archive_context)

    @server.mcp.prompt("timeline")
    def timeline(topic: str) -> List[Dict[str, Any]]:
        """Extract a dated chronology for a Wikipedia subject."""
        return _timeline_body(topic, archive_context)

    @server.mcp.prompt("map")
    def concept_map(topic: str) -> List[Dict[str, Any]]:
        """Map a concept and its adjacent Wikipedia topics."""
        return _map_body(topic, archive_context)
