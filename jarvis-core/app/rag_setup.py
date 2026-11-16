"""
RAG setup for the CEO profile (CV + portfolio notes) in ChromaDB.
 
What it does:
- ``ingest()`` reads every ``.txt``/``.md`` file in the knowledge directory (default
  ``app/knowledge/``, e.g. ``boss_cv.txt``), splits it into one chunk per project / role /
  section, embeds the chunks with the configured backend (Ollama, OpenAI or the offline
  fallback) and stores them in a persistent ChromaDB collection under ``CHROMA_PERSIST_DIR``.
- ``retrieve(query)`` embeds a tender brief and returns the best-matching chunks (projects
  first) with a 0..1 similarity score. It ingests on first use if the collection is empty,
  so no manual step is needed after a rebuild.
- Context-separated memory: ``remember(collection, ...)`` writes notes (email summaries, tender
  notes, briefings) into one of ``MEMORY_COLLECTIONS`` and ``recall(collection, query)`` reads
  them back. Each context gets its own ChromaDB collection so an email digest never pollutes a
  tender search. The CV/pitch knowledge stays in ``ceo-profile`` (see ``PROFILE_COLLECTION``).
 
Run by hand (inside the core container):
 
    python -m app.rag_setup                 # (re)ingest and list the chunks
    python -m app.rag_setup --dry-run       # parse only: no Ollama, no ChromaDB (works on the host)
    python -m app.rag_setup --query "smart building IoT energy"
 
Design notes:
- Embeddings come from a backend chosen by ``EMBED_PROVIDER`` (or automatically):
  cloud (``IS_CLOUD=true``) uses ``openai``/``text-embedding-3-small`` when ``OPENAI_API_KEY``
  is set, and otherwise the offline ``hash`` fallback so the server always starts; local runs use
  ``ollama``/``nomic-embed-text`` exactly as before. ``groq`` maps to the fallback because Groq
  serves no embeddings.
- Embeddings are computed here and passed to ChromaDB explicitly. ChromaDB's default embedding
  function downloads an ONNX model, and ``backend`` has no internet (CLAUDE.md section 5).
- Ollama is called with the standard library (``urllib``), so no new dependency is needed, and
  with proxies disabled: Ollama is an internal service and must never go through Squid. The
  OpenAI call uses the same stdlib client (with the environment proxy, as it is an external API).
- Vectors are L2-normalised before storage, so ChromaDB's default (squared L2) distance ranks
  exactly like cosine similarity and ``score = 1 - distance / 2``.
- The collection name includes the embedding backend/model. Changing ``EMBED_MODEL``,
  ``EMBED_PROVIDER`` or the provider's default therefore starts a fresh collection instead of
  mixing vector sizes (CLAUDE.md: treat it as a migration).
- The lines above the first section heading of a CV (name, phone, e-mail, links) are NOT
  indexed: contact details have no business in a prompt or a generated pitch.
- ``chromadb`` is imported lazily so the API starts fast and host tests run without it.
"""
 
from __future__ import annotations
 
import argparse
import hashlib
import json
import logging
import math
import os
import re
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any
 
logger = logging.getLogger("jarvis.rag")
 
KNOWLEDGE_SUFFIXES = (".txt", ".md")
MAX_FILE_BYTES = 512_000
MAX_CHUNK_CHARS = 1000
MAX_CHUNKS = 400
EMBED_BATCH = 16
# Covers Ollama unloading the chat model and loading the embedding model on CPU, or a slow
# embedding API response.
EMBED_TIMEOUT_S = 180.0
DEFAULT_SUBJECT = "our CEO"

# Cloud deployment (Railway): no Ollama container, so embeddings come from a cloud API or the
# offline fallback. Kept in step with app.crew_factory.IS_CLOUD.
IS_CLOUD = os.environ.get("IS_CLOUD", "false").strip().lower() == "true"

# --- Context collections -----------------------------------------------------------------------
# The CEO profile / pitch knowledge stays in its own collection; the three memory contexts are
# separate so retrieval in one context cannot surface text from another.
PROFILE_COLLECTION = "ceo-profile"
MEMORY_COLLECTIONS = ("email_memory", "tender_memory", "briefing_memory")
# Friendly aliases the agent may use in a tool call -> canonical collection key.
COLLECTION_ALIASES = {
    "email": "email_memory", "emails": "email_memory", "inbox": "email_memory",
    "mail": "email_memory", "email_memory": "email_memory",
    "tender": "tender_memory", "tenders": "tender_memory", "bids": "tender_memory",
    "procurement": "tender_memory", "tender_memory": "tender_memory",
    "briefing": "briefing_memory", "briefings": "briefing_memory",
    "morning_briefing": "briefing_memory", "briefing_memory": "briefing_memory",
}
MAX_MEMORY_CHARS = 2_000
MAX_MEMORY_ITEMS = 50
 
_BULLETS = ("•", "-", "–", "*", "·", "▪", "●")
_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z.'-]*( [A-Za-z][A-Za-z.'-]*){1,3}$")
 
_client_lock = threading.Lock()
_client: Any = None
 
# Internal call: ignore HTTP(S)_PROXY from the environment.
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
 
 
class ProfileStoreError(RuntimeError):
    """The CEO profile store can't be used (no knowledge files, Ollama or ChromaDB failure)."""
 
 
@dataclass(frozen=True)
class Chunk:
    """One indexed piece of the profile."""
 
    id: str
    title: str      # project / employer / section name, unique per entry
    section: str    # CV section it came from, e.g. "Flagship Projects"
    kind: str       # "project" (a concrete engagement) or "section" (skills, patents, ...)
    text: str
    source: str     # file name
    subject: str    # person the profile is about
 
 
@dataclass(frozen=True)
class Evidence:
    """A retrieved chunk with its similarity to the query (1.0 = identical direction)."""
 
    title: str
    section: str
    kind: str
    text: str
    score: float
    subject: str
 
 
# --- Configuration -----------------------------------------------------------------------------
def _knowledge_dir() -> Path:
    return Path(os.environ.get("KNOWLEDGE_DIR") or Path(__file__).resolve().parent / "knowledge")
 
 
def _persist_dir() -> str:
    return os.environ.get("CHROMA_PERSIST_DIR", "/data/chroma")
 
 
def _ollama_url() -> str:
    url = os.environ.get("OLLAMA_URL", "http://ollama:11434").rstrip("/")
    if not url.startswith(("http://", "https://")):
        raise ProfileStoreError("OLLAMA_URL must be an http(s) URL")
    return url
 
 
def _embed_model() -> str:
    """Model name for the active backend (``EMBED_MODEL`` overrides)."""
    configured = (os.environ.get("EMBED_MODEL") or "").strip()
    if configured:
        return configured
    return "text-embedding-3-small" if _embed_provider() == "openai" else "nomic-embed-text"


# --- Embedding backend ---------------------------------------------------------------------------
# Groq serves no embeddings, and the cloud demo has no Ollama. These values select the offline
# fallback: deterministic hashed bag-of-words vectors. It is a lexical match (shared words score
# higher), not a semantic one, but every retrieval path keeps working without a network.
HASH_EMBED_PROVIDERS = frozenset({"hash", "groq", "mock", "none"})
HASH_EMBED_DIM = 512
DEFAULT_EMBED_PROVIDER = "ollama"
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_hash_notice_logged = False


def _embed_provider() -> str:
    """Embedding backend name.

    ``EMBED_PROVIDER`` wins when set. Otherwise: cloud uses ``openai`` if ``OPENAI_API_KEY`` is
    present and the offline ``hash`` fallback if not (so startup never fails on a missing key);
    local keeps ``ollama``.
    """
    configured = (os.environ.get("EMBED_PROVIDER") or "").strip().lower()
    if configured:
        return configured
    if IS_CLOUD:
        return "openai" if (os.environ.get("OPENAI_API_KEY") or "").strip() else "hash"
    return DEFAULT_EMBED_PROVIDER


def _uses_hash_embeddings() -> bool:
    return _embed_provider() in HASH_EMBED_PROVIDERS


def _embed_signature() -> str:
    """Short name that identifies the vector space, used in collection names."""
    return "hash" if _uses_hash_embeddings() else _embed_model()


def collection_name(base: str = PROFILE_COLLECTION) -> str:
    """ChromaDB collection name for ``base`` (``ceo-profile``, ``email_memory``, ...).

    The embedding backend is part of the name: changing ``EMBED_MODEL`` or ``EMBED_PROVIDER``
    starts a fresh collection instead of mixing vectors of different sizes.
    """
    model = re.sub(r"[^A-Za-z0-9]+", "-", _embed_signature()).strip("-") or "default"
    safe_base = re.sub(r"[^A-Za-z0-9_-]+", "-", base).strip("-") or PROFILE_COLLECTION
    return f"{safe_base}-{model}"[:60].rstrip("-")


def normalise_collection(value: str | None) -> str:
    """Map a context name/alias to a canonical memory collection, or raise ``ProfileStoreError``."""
    key = re.sub(r"[^a-z0-9_]+", "_", (value or "").strip().lower()).strip("_")
    if key in MEMORY_COLLECTIONS:
        return key
    resolved = COLLECTION_ALIASES.get(key)
    if resolved is None:
        allowed = ", ".join(MEMORY_COLLECTIONS)
        raise ProfileStoreError(f"Unknown memory context {value!r}. Use one of: {allowed}")
    return resolved
 
 
# --- Parsing & chunking (pure) -----------------------------------------------------------------
def _is_heading(line: str) -> bool:
    """A CV section heading: a short ALL-CAPS line such as ``FLAGSHIP PROJECTS``."""
    letters = [c for c in line if c.isalpha()]
    return (
        4 <= len(letters) and len(line) <= 60 and line == line.upper()
        and " | " not in line and not line.startswith(_BULLETS)
        and not line.endswith((".", ",", ";", ":")) and not any(c.isdigit() for c in line)
    )
 
 
def _is_entry_header(line: str) -> bool:
    """First lines of a project/role, e.g. ``HSBC | London, UK | Oct 2022 – Aug 2023``."""
    return " | " in line and not line.startswith(_BULLETS) and not line.lower().startswith("tech:")
 
 
def _subject_name(first_line: str) -> str:
    """Whose profile this is: ``CEO_NAME`` if set, else the CV's first line if it looks like a
    person's name, else a neutral fallback."""
    configured = " ".join(os.environ.get("CEO_NAME", "").split())[:80]
    if configured:
        return configured
    cleaned = re.sub(r"^[#\s*•\-–]+", "", first_line)
    cleaned = re.split(r"[-–|:]", cleaned)[0].strip()
    return cleaned.title() if _NAME_RE.fullmatch(cleaned) else (
        first_line.title() if _NAME_RE.fullmatch(first_line) else DEFAULT_SUBJECT
    )
 
 
def _pack(lines: list[str], limit: int = MAX_CHUNK_CHARS) -> list[str]:
    """Join lines into texts of at most ``limit`` characters, breaking only between lines."""
    parts: list[str] = []
    current = ""
    for line in lines:
        line = line[:limit]
        if current and len(current) + 1 + len(line) > limit:
            parts.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current:
        parts.append(current)
    return parts
 
 
def _split_entries(body: list[str]) -> tuple[list[str], list[list[str]]]:
    """Split a section body into leading lines and entries (each starting at a header line).
 
    A header directly after another header belongs to the same entry (CVs put the employer
    line and the job-title line next to each other).
    """
    lead: list[str] = []
    entries: list[list[str]] = []
    prev_header = False
    for line in body:
        header = _is_entry_header(line)
        if header and not prev_header:
            entries.append([line])
        elif entries:
            entries[-1].append(line)
        else:
            lead.append(line)
        prev_header = header
    return lead, entries
 
 
def _chunk_id(source: str, title: str, text: str) -> str:
    return hashlib.sha256(f"{source}\x00{title}\x00{text}".encode()).hexdigest()[:32]


_MD_PROJECT_RE = re.compile(r"^#+\s*PROJECT(?:\s*\d+)?\s*:\s*(.+)$", re.IGNORECASE)


def parse_profile(text: str, source: str) -> list[Chunk]:
    """Split a CV-style text or markdown project portfolio into chunks:
    one per project/role, one per plain section.

    Files without section headings (e.g. free-form portfolio notes) fall back to
    paragraph chunks titled after the file.
    """
    lines = [" ".join(raw.split()) for raw in text.replace("\r\n", "\n").split("\n")]
    first = next((ln for ln in lines if ln), "")
    subject = _subject_name(first)
    stem = Path(source).stem.replace("_", " ").replace("-", " ").title()

    chunks: list[Chunk] = []

    def add(title: str, section: str, kind: str, body: list[str]) -> None:
        for part in _pack(body):
            chunks.append(Chunk(_chunk_id(source, title, part), title[:120], section[:80], kind,
                                part, source, subject))

    # Fast path: detect markdown project entries (e.g. "## PROJECT 1: ...")
    md_project_indices = [
        i for i, ln in enumerate(lines) if _MD_PROJECT_RE.match(ln)
    ]
    if md_project_indices:
        current_section = "Flagship Projects"
        for ln in lines[:md_project_indices[0]]:
            if ln.startswith("#"):
                clean_hd = re.sub(r"^[#\s*•\-–]+", "", ln).strip()
                if " - " in clean_hd:
                    parts = clean_hd.split(" - ", 1)
                    if not subject or subject == DEFAULT_SUBJECT:
                        sub_candidate = parts[0].strip()
                        if _NAME_RE.fullmatch(sub_candidate):
                            subject = sub_candidate.title()
                    current_section = parts[1].strip().title()
                elif clean_hd:
                    current_section = clean_hd.title()

        for idx, start_i in enumerate(md_project_indices):
            header_line = lines[start_i]
            m = _MD_PROJECT_RE.match(header_line)
            raw_title = m.group(1).strip() if m else "Project"
            clean_title = re.sub(r"\s*\([^)]*\)$", "", raw_title).strip() or raw_title

            end_i = md_project_indices[idx + 1] if idx + 1 < len(md_project_indices) else len(lines)
            entry_lines: list[str] = []
            for ln in lines[start_i + 1:end_i]:
                if not ln or ln in ("---", "***", "___"):
                    continue
                if ln.startswith("#") and not _MD_PROJECT_RE.match(ln):
                    continue
                entry_lines.append(ln)

            body = [f"Title: {clean_title}", *entry_lines]
            add(clean_title, current_section, "project", body)

        return chunks[:MAX_CHUNKS]

    # Group lines under headings. The very first line is the person's name, never a heading.
    sections: list[tuple[str, list[str]]] = []
    seen_first = False
    for line in lines:
        if not line:
            continue
        if not seen_first:
            seen_first = True
            sections.append(("", [line]))
            continue
        if _is_heading(line):
            sections.append((line.title(), []))
        else:
            sections[-1][1].append(line)
 
    if len(sections) == 1:  # no headings at all: paragraph fallback, keep everything
        paragraphs = [p for p in re.split(r"\n\s*\n", text.replace("\r\n", "\n")) if p.strip()]
        add(stem, stem, "section", [" ".join(p.split()) for p in paragraphs])
        return chunks[:MAX_CHUNKS]
 
    used_titles: dict[str, int] = {}
    for heading, body in sections[1:]:  # sections[0] is the contact preamble: skipped
        if not body:
            continue
        lead, entries = _split_entries(body)
        if lead:
            add(heading, heading, "section", lead)
        for entry in entries:
            segments = [s.strip() for s in entry[0].split(" | ")]
            title = segments[0][:100] or heading
            # Same employer twice (two stints): tell them apart by the period.
            if title.lower() in used_titles or sum(
                1 for e in entries if e[0].split(" | ")[0].strip().lower() == title.lower()
            ) > 1:
                title = f"{title} ({segments[-1]})"[:120]
            used_titles[title.lower()] = 1
            add(title, heading, "project", entry)
    return chunks[:MAX_CHUNKS]
 
 
def load_chunks() -> list[Chunk]:
    """Read and chunk every knowledge file. Raises ``ProfileStoreError`` if there is nothing."""
    folder = _knowledge_dir()
    try:
        files = sorted(p for p in folder.iterdir()
                       if p.is_file() and p.suffix.lower() in KNOWLEDGE_SUFFIXES)
    except OSError as exc:
        raise ProfileStoreError(f"Knowledge directory is not readable: {folder.name}") from exc
    chunks: list[Chunk] = []
    for path in files:
        if path.stat().st_size > MAX_FILE_BYTES:
            logger.warning("Skipping %s: larger than %d bytes", path.name, MAX_FILE_BYTES)
            continue
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        found = parse_profile(text, path.name)
        logger.info("Parsed %s into %d chunks", path.name, len(found))
        chunks.extend(found)
    if not chunks:
        raise ProfileStoreError("No profile text found: add boss_cv.txt to app/knowledge/")
    # The subject comes from the first file that names one (the CV sorts before portfolio notes).
    subject = next((c.subject for c in chunks if c.subject != DEFAULT_SUBJECT), DEFAULT_SUBJECT)
    return [Chunk(c.id, c.title, c.section, c.kind, c.text, c.source, subject)
            for c in chunks[:MAX_CHUNKS]]
 
 
# --- Embeddings (Ollama, OpenAI, or the offline hashed fallback) --------------------------------
def _normalise(vector: Any) -> list[float]:
    if not isinstance(vector, list) or not vector:
        raise ProfileStoreError("The embedding backend returned an invalid embedding")
    values = [float(v) for v in vector]
    norm = math.sqrt(sum(v * v for v in values))
    if not math.isfinite(norm) or norm == 0.0:
        raise ProfileStoreError("The embedding backend returned an invalid embedding")
    return [v / norm for v in values]


def _hash_embed(text: str) -> list[float]:
    """Deterministic bag-of-words vector: hashed token counts, L2-normalised.

    A lexical fallback for deployments with neither Ollama nor an embedding API (the 1 GB cloud
    demo). Documents sharing words with the query score higher; there is no semantic meaning to
    the directions. It must stay deterministic across processes, so hashlib is used (Python's
    ``hash`` is salted per process).
    """
    vector = [0.0] * HASH_EMBED_DIM
    for token in _TOKEN_RE.findall(text.lower()):
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        index = int.from_bytes(digest[:4], "big") % HASH_EMBED_DIM
        vector[index] += 1.0 if digest[4] & 1 else -1.0
    return _normalise(vector)


def _openai_embed(texts: list[str]) -> list[list[float]]:
    """Embed texts with the OpenAI embeddings API (one stdlib HTTP call per batch, no SDK)."""
    key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if not key:
        raise ProfileStoreError(
            "OPENAI_API_KEY is not set; set EMBED_PROVIDER=hash for the offline fallback"
        )
    base = (os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
    body = json.dumps({"model": _embed_model(), "input": texts}).encode("utf-8")
    request = urllib.request.Request(  # noqa: S310 - default is https
        f"{base}/embeddings", data=body, method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        # Unlike Ollama, this is an external API, so the environment proxy is allowed.
        with urllib.request.urlopen(request, timeout=EMBED_TIMEOUT_S) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        logger.error("OpenAI embedding call failed: HTTP %d", exc.code)
        raise ProfileStoreError("The OpenAI embedding request was rejected") from exc
    except (OSError, ValueError) as exc:
        logger.error("OpenAI embedding call failed: %s", exc.__class__.__name__)
        raise ProfileStoreError("Could not reach the OpenAI embedding API") from exc
    items = payload.get("data") if isinstance(payload, dict) else None
    if (not isinstance(items, list) or len(items) != len(texts)
            or not all(isinstance(item, dict) for item in items)):
        raise ProfileStoreError("OpenAI returned an unexpected embedding response")
    ordered = sorted(items, key=lambda item: int(item.get("index", 0)))
    return [_normalise(item.get("embedding")) for item in ordered]


def _embed(texts: list[str]) -> list[list[float]]:
    """Embed texts with the configured backend; returns unit-length vectors."""
    global _hash_notice_logged
    if _uses_hash_embeddings():
        if not _hash_notice_logged:
            logger.info("Embeddings: offline hashed fallback (EMBED_PROVIDER=%s); "
                        "lexical match only, no semantic model", _embed_provider())
            _hash_notice_logged = True
        return [_hash_embed(text) for text in texts]
    if _embed_provider() == "openai":
        vectors: list[list[float]] = []
        for start in range(0, len(texts), EMBED_BATCH):
            vectors.extend(_openai_embed(texts[start:start + EMBED_BATCH]))
        return vectors
    vectors: list[list[float]] = []
    for start in range(0, len(texts), EMBED_BATCH):
        batch = texts[start:start + EMBED_BATCH]
        body = json.dumps({"model": _embed_model(), "input": batch}).encode("utf-8")
        request = urllib.request.Request(  # noqa: S310 - scheme checked in _ollama_url()
            f"{_ollama_url()}/api/embed", data=body, method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with _opener.open(request, timeout=EMBED_TIMEOUT_S) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as exc:
            # 404 here almost always means the embedding model has not been pulled.
            logger.error("Embedding call failed: HTTP %d (is %s pulled?)", exc.code, _embed_model())
            raise ProfileStoreError("The embedding model is not available in Ollama") from exc
        except (OSError, ValueError) as exc:
            logger.error("Embedding call failed: %s", exc.__class__.__name__)
            raise ProfileStoreError("Could not reach the embedding model") from exc
        raw = payload.get("embeddings") if isinstance(payload, dict) else None
        if not isinstance(raw, list) or len(raw) != len(batch):
            raise ProfileStoreError("Ollama returned an unexpected embedding response")
        vectors.extend(_normalise(v) for v in raw)
    return vectors
 
 
# nomic-embed-text is trained with task prefixes; using them measurably improves retrieval.
# The hashed fallback and OpenAI embeddings do not use them.
def _uses_task_prefixes() -> bool:
    return _embed_provider() == "ollama"


def _doc_text(chunk: Chunk) -> str:
    text = f"{chunk.title} ({chunk.section})\n{chunk.text}"
    return f"search_document: {text}" if _uses_task_prefixes() else text


def _query_text(query: str) -> str:
    return f"search_query: {query}" if _uses_task_prefixes() else query
 
 
# --- ChromaDB ----------------------------------------------------------------------------------
def _collection(base: str = PROFILE_COLLECTION) -> Any:
    global _client
    with _client_lock:
        if _client is None:
            import chromadb
            from chromadb.config import Settings

            _client = chromadb.PersistentClient(
                path=_persist_dir(), settings=Settings(anonymized_telemetry=False)
            )
        # embedding_function=None: we always pass vectors ourselves, so ChromaDB must never
        # fall back to its default (ONNX download) embedder.
        return _client.get_or_create_collection(
            name=collection_name(base), embedding_function=None
        )
 
 
def ingest() -> list[Chunk]:
    """(Re)build the profile collection from the knowledge files. Idempotent: unchanged chunks
    keep their ids, and chunks that no longer exist in the files are removed."""
    chunks = load_chunks()
    try:
        vectors = _embed([_doc_text(c) for c in chunks])
        collection = _collection()
        existing = set(collection.get(include=[])["ids"])
        collection.upsert(
            ids=[c.id for c in chunks],
            embeddings=vectors,
            documents=[c.text for c in chunks],
            metadatas=[{"title": c.title, "section": c.section, "kind": c.kind,
                        "source": c.source, "subject": c.subject} for c in chunks],
        )
        stale = sorted(existing - {c.id for c in chunks})
        if stale:
            collection.delete(ids=stale)
    except ProfileStoreError:
        raise
    except Exception as exc:
        logger.error("Profile ingest failed: %s", exc.__class__.__name__)
        raise ProfileStoreError("Could not write the profile to the vector store") from exc
    logger.info("Profile ingested: %d chunks into %s", len(chunks), collection_name())
    return chunks
 
 
def select_evidence(ranked: list[Evidence], k: int) -> list[Evidence]:
    """Pick ``k`` items from a best-first list: concrete projects first, then the rest.
 
    Skills and summary sections are keyword-dense and would otherwise crowd out the projects,
    but a pitch needs a real engagement to point to.
    """
    projects = [e for e in ranked if e.kind == "project"][:max(k - 1, 1)]
    others = [e for e in ranked if e.kind != "project"]
    chosen = projects + others[:max(k - len(projects), 0)]
    if len(chosen) < k:  # not enough non-project sections: top up with more projects
        chosen += [e for e in ranked if e.kind == "project" and e not in chosen][:k - len(chosen)]
    return chosen[:k]
 
 
def retrieve(query: str, k: int = 4) -> list[Evidence]:
    """Return the profile chunks most relevant to ``query`` (projects first), best first."""
    try:
        collection = _collection()
        if collection.count() == 0:
            logger.info("Profile collection is empty: ingesting now")
            ingest()
        total = collection.count()
        if total == 0:
            raise ProfileStoreError("The profile store is empty")
        vector = _embed([_query_text(query[:4000])])[0]
        result = collection.query(
            query_embeddings=[vector], n_results=min(max(k * 3, 10), total),
            include=["documents", "metadatas", "distances"],
        )
    except ProfileStoreError:
        raise
    except Exception as exc:
        logger.error("Profile retrieval failed: %s", exc.__class__.__name__)
        raise ProfileStoreError("Could not search the profile store") from exc
 
    ranked: list[Evidence] = []
    for text, meta, distance in zip(result["documents"][0], result["metadatas"][0],
                                    result["distances"][0], strict=True):
        meta = meta or {}
        score = max(0.0, min(1.0, 1.0 - float(distance) / 2.0))
        ranked.append(Evidence(
            title=str(meta.get("title", "")), section=str(meta.get("section", "")),
            kind=str(meta.get("kind", "section")), text=str(text or ""),
            score=round(score, 3), subject=str(meta.get("subject", DEFAULT_SUBJECT)),
        ))
    return select_evidence(ranked, k)


# --- Context memory (email / tender / briefing) -------------------------------------------------
def _memory_id(collection: str, index: int, text: str) -> str:
    digest = hashlib.sha256(f"{collection}:{index}:{text}".encode()).hexdigest()[:24]
    return f"{collection}-{digest}"


def remember(
    collection: str,
    texts: list[str],
    metadatas: list[dict[str, Any]] | None = None,
    source: str = "manual",
) -> int:
    """Write notes into a context memory collection. Returns the number of items stored.

    Idempotent for identical text: the id is derived from the collection, position and text, so a
    repeated briefing (same text) overwrites instead of duplicating. Best-effort callers should
    catch ``ProfileStoreError``: memory must never break the feature that produced the note.
    """
    key = normalise_collection(collection)
    if metadatas is not None and len(metadatas) != len(texts):
        raise ProfileStoreError("metadatas must match texts one-to-one")
    pairs = [
        (str(text).strip()[:MAX_MEMORY_CHARS], (metadatas[i] if metadatas else {}))
        for i, text in enumerate(texts)
        if str(text or "").strip()
    ][:MAX_MEMORY_ITEMS]
    if not pairs:
        return 0
    cleaned = [text for text, _ in pairs]
    metas = [meta for _, meta in pairs]
    try:
        vectors = _embed([_doc_text(Chunk(
            id="", title=key, section=key, kind="memory", text=text, source=source,
            subject=DEFAULT_SUBJECT,
        )) for text in cleaned])
        collection_obj = _collection(key)
        ids = [_memory_id(key, i, text) for i, text in enumerate(cleaned)]
        collection_obj.upsert(
            ids=ids,
            embeddings=vectors,
            documents=cleaned,
            metadatas=[
                {"context": key, "source": str((meta or {}).get("source", source)),
                 **{k: str(v)[:500] for k, v in (meta or {}).items() if k != "source"}}
                for meta in metas
            ],
        )
    except ProfileStoreError:
        raise
    except Exception as exc:
        logger.error("Memory write failed for %s: %s", key, exc.__class__.__name__)
        raise ProfileStoreError("Could not write to the memory store") from exc
    logger.info("Stored %d item(s) in %s", len(cleaned), collection_name(key))
    return len(cleaned)


def recall(collection: str, query: str, k: int = 4) -> list[dict[str, Any]]:
    """Return the memory notes in ``collection`` most relevant to ``query``, best first."""
    key = normalise_collection(collection)
    try:
        collection_obj = _collection(key)
        total = collection_obj.count()
        if total == 0:
            return []
        vector = _embed([_query_text(query[:4000] or key)])[0]
        result = collection_obj.query(
            query_embeddings=[vector], n_results=min(max(k, 1), total),
            include=["documents", "metadatas", "distances"],
        )
    except ProfileStoreError:
        raise
    except Exception as exc:
        logger.error("Memory recall failed for %s: %s", key, exc.__class__.__name__)
        raise ProfileStoreError("Could not search the memory store") from exc

    hits: list[dict[str, Any]] = []
    for text, meta, distance in zip(result["documents"][0], result["metadatas"][0],
                                    result["distances"][0], strict=True):
        hits.append({
            "collection": key,
            "text": str(text or ""),
            "score": round(max(0.0, min(1.0, 1.0 - float(distance) / 2.0)), 3),
            "metadata": dict(meta or {}),
        })
    return hits


def memory_stats() -> dict[str, int]:
    """Item count per memory collection (used by the dashboard/debug output)."""
    stats: dict[str, int] = {}
    for key in MEMORY_COLLECTIONS:
        try:
            stats[key] = int(_collection(key).count())
        except Exception as exc:  # noqa: BLE001 - a stats call must never raise
            logger.warning("Could not count %s: %s", key, exc.__class__.__name__)
            stats[key] = -1
    return stats
 
 
# --- CLI ---------------------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest the CEO profile into ChromaDB.")
    parser.add_argument("--dry-run", action="store_true",
                        help="parse and list chunks only (no Ollama, no ChromaDB)")
    parser.add_argument("--query", help="after ingesting, show what this query retrieves")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        chunks = load_chunks() if args.dry_run else ingest()
        # Titles only: never log document text.
        for chunk in chunks:
            logger.info("chunk %-8s %-22s %s (%d chars)", chunk.kind, chunk.section[:22],
                        chunk.title, len(chunk.text))
        logger.info("%d chunks, subject: %s", len(chunks), chunks[0].subject)
        if args.query and not args.dry_run:
            for item in retrieve(args.query):
                logger.info("match %.3f  %s (%s)", item.score, item.title, item.section)
    except ProfileStoreError as exc:
        logger.error("%s", exc)
        return 1
    return 0
 
 
if __name__ == "__main__":
    raise SystemExit(main())