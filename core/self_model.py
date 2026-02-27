import ast
import os
import hashlib
from typing import Optional

import chromadb
from chromadb.utils import embedding_functions
from langchain_google_genai import ChatGoogleGenerativeAI
from dotenv import load_dotenv

load_dotenv()

# ── ChromaDB setup ────────────────────────────────────────────────────────────
CHROMA_PATH     = "./chroma_db"
COLLECTION_NAME = "aegis_self_model"

ef = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name="all-MiniLM-L6-v2"
)
_chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
collection = _chroma_client.get_or_create_collection(
    name=COLLECTION_NAME, embedding_function=ef
)

# ── Repo layout ───────────────────────────────────────────────────────────────
SKIP_DIRS = {
    ".git", "__pycache__", "chroma_db", "aegis_workspace",
    ".venv", "node_modules", ".mypy_cache", ".pytest_cache",
}
# Utility/config files — skip even if discovered
SKIP_FILES = {"setup.py", "conftest.py", "__init__.py"}

# Injection sentinel for _persist_role().
# MUST be built from parts — never written as a complete string literal anywhere
# in this file. If the full string appeared literally, source.replace() would
# find it twice (once in MODULE_ROLES, once here) and corrupt the file.
_SENTINEL = "    # <<" + "AUTO_DISCOVERED" + ">>"

# Files whose FULL CONTENT is always injected into every evolution prompt.
# These define the contracts every new module must conform to.
ALWAYS_INJECT_FILES = [
    "services/hands.py",                      # @tool pattern + all existing tools
    "core/event_bus.py",                      # event contracts + topic constants
    "core/memory_client.py",                  # the only safe way to write memory
    "services/social/platform_adapter.py",    # interface for new social platforms
]

# ── Module Roles ──────────────────────────────────────────────────────────────
# This dict is the living record of every known module.
# New entries are auto-written here by _persist_role() after discovery.
# DO NOT remove the <<AUTO_DISCOVERED>> sentinel — it is the injection point.
MODULE_ROLES: dict[str, str] = {
    # ── Core ──────────────────────────────────────────────────────────────────
    "core/brain.py":                       "Chat persona. Two-pass LLM chain: inner monologue then spoken response. VAD gates tone.",
    "core/memory.py":                      "Long-term GraphRAG. NetworkX MultiDiGraph. Knowledge edge extraction from conversations.",
    "core/memory_daemon.py":               "Async write serializer. ALL writes to memory.json go through here. Never bypass.",
    "core/memory_client.py":               "Public memory write API. Call commit_edges_sync() — never touch memory.json directly.",
    "core/working_memory.py":              "Token-aware scratchpad for active deep_dive sessions. Auto-compresses at threshold.",
    "core/core_store.py":                  "ChromaDB: permanent beliefs + behaviors. Written by sleep.py, read by all shards.",
    "core/knowledge_store.py":             "ChromaDB: factual memories + GraphRAG index. retrieve() is the main read interface.",
    "core/event_bus.py":                   "Async pub/sub backbone. All inter-shard communication. Typed event dataclasses.",
    "core/self_model.py":                  "Architectural self-awareness. File tree + ChromaDB patterns. Feeds evolution prompts. Auto-discovers new modules.",
    # ── Services ──────────────────────────────────────────────────────────────
    "services/brain.py":                   "Chat entry point. Calls update_emotion then generate_response.",
    "services/wander.py":                  "Curiosity module. Picks topics from GraphRAG subgraphs, browses HN/4chan.",
    "services/deep_dive.py":               "Primary research brain. Iterative tool loop with WorkingMemory. Triggers EVOLUTION_REQUIRED.",
    "services/evolution.py":               "SWE agent. Docker sandbox, write, test, push, PR. Engineering autopsy on completion.",
    "services/hands.py":                   "All @tool definitions for file I/O, Docker, GitHub, and self-reading.",
    "services/sleep.py":                   "REM consolidation. GraphRAG edges into new beliefs/behaviors in core_store.",
    "services/social_shard.py":            "Social presence. Subscribes to TOPIC_OPINION_FORMED, posts via PlatformAdapter.",
    "services/social/platform_adapter.py": "Abstract interface all social platform adapters must implement.",
    "chat.py": "Terminal client facilitates user interaction with the Aegis chat API, displaying replies and VAD states.",
    "client.py": "A terminal client continuously sends user input to the Aegis chat API, displaying AI replies and VAD states.",
    "main.py": "Aegis's main application orchestrates AI services, manages global state, and initiates autonomous cognitive loops.",
    "reflection.py": "Personality evolution module updates Aegis's core traits and behavioral rules after intense emotional experiences.",
    "surgery.py": "A script performs surgery to delete 'Transformers' or 'Megan Fox' traits from Aegis's core personality database.",
    "services/dynamic_tools.py": "Dynamic tools for LangChain agents, enabling web requests, scraping, and JSON processing.",
    "services/forge.py": "Forge performs post-execution analysis, extracting and storing engineering lessons from task attempts.",
    "services/social/hackernews_adapter.py": "HackerNewsAdapter manages authenticated and rate-limited interactions with the Hacker News social platform.",
    "services/social/opinion_gate.py": "Aegis's opinion gate evaluates social media post suitability based on content metrics and platform rate limits.",
    "services/social/social_shard.py": "The SocialShard manages AI's social interactions across platforms, processing opinions, engaging with content, and simulating doomscrolling.",
    "services/social/threads_adapter.py": "ThreadsAdapter provides an interface for Aegis to interact with the Threads social media platform.",
    "services/social/x_adapter.py": "XAdapter fetches and filters social media posts from the X platform using `twscrape` and `tweepy`.",
    # <<AUTO_DISCOVERED>>
}

# ── Architectural Patterns ────────────────────────────────────────────────────
# Constitutional rules — curated, not auto-generated.
# Add new ones manually when Aegis's architecture gains new conventions.
ARCHITECTURAL_PATTERNS = [
    {
        "id": "pattern_new_tool",
        "text": (
            "PATTERN — Adding a new @tool Aegis can use: "
            "Define it in services/hands.py using the @tool decorator from langchain.tools. "
            "The function docstring IS the tool description — write it precisely. "
            "Then import and add it to: (1) tools list in services/deep_dive.py, "
            "(2) swe_tools list in services/evolution.py."
        ),
    },
    {
        "id": "pattern_memory_write",
        "text": (
            "PATTERN — Writing to Aegis's memory graph: "
            "NEVER write to memory.json directly. NEVER call memory.save_graph() from a shard. "
            "Always use: from core.memory_client import commit_edges_sync, "
            "then commit_edges_sync(edges=[{source, relation, target, valence}], new_nodes=[...]). "
            "This routes through memory_daemon.py which handles locking and ChromaDB dirty-node indexing."
        ),
    },
    {
        "id": "pattern_new_platform",
        "text": (
            "PATTERN — Adding a new social platform: "
            "Create services/social/{platform}_adapter.py implementing PlatformAdapter. "
            "Required methods: on_startup, on_shutdown, fetch_feed, fetch_thread, "
            "post_reply, post_original, get_own_posts, rate_limit_config. "
            "Then instantiate and add to adapters list in social_shard.py _run_standalone()."
        ),
    },
    {
        "id": "pattern_event_bus",
        "text": (
            "PATTERN — Communication between shards: "
            "Never import one shard directly into another. Use the event bus. "
            "Step 1: Add a @dataclass event and TOPIC_ constant in core/event_bus.py. "
            "Step 2: Publisher: await get_bus().publish(TOPIC_X, MyEvent(...)). "
            "Step 3: Subscriber: get_bus().subscribe(TOPIC_X, self._handler) in __init__. "
            "Handler must be: async def _handler(self, event: MyEvent)."
        ),
    },
    {
        "id": "pattern_evolution_trigger",
        "text": (
            "PATTERN — Triggering self-evolution from deep_dive: "
            "Output the literal string EVOLUTION_REQUIRED followed by a full description: "
            "what failed, what was attempted, what the new tool/module must do, what interface it should follow. "
            "deep_dive.py catches this, ejects the research loop, calls evolution.trigger_swe_agent()."
        ),
    },
    {
        "id": "pattern_belief_behavior",
        "text": (
            "PATTERN — Storing a permanent belief or reactive behavior: "
            "Call core.core_store.add_trait(text, source_event, trait_type) "
            "where trait_type is belief (worldview rule) or behavior (reactive protocol). "
            "All shards retrieve these via retrieve_relevant_traits(context) to shape tone."
        ),
    },
    {
        "id": "pattern_vad_shift",
        "text": (
            "PATTERN — Shifting Aegis's emotional state (VAD): "
            "state.json holds valence (0-1), arousal (0-1), dominance (0-1). "
            "Read: brain.load_state(). "
            "Shift from a shard: publish VadShiftEvent to TOPIC_VAD_SHIFT on the event bus. "
            "Never write state.json directly from a shard."
        ),
    },
    {
        "id": "pattern_docker_sandbox",
        "text": (
            "PATTERN — Docker sandbox for testing new code: "
            "1. boot_dev_server() — persistent container, workspace at /workspace. "
            "2. run_terminal_command('pip install X') — persists until shutdown. "
            "3. write_local_file(filename, content) — writes to aegis_workspace/ mapped to /workspace. "
            "4. run_terminal_command('python script.py') — execute and read output. "
            "HARD RULE: after write_local_file, NEXT action MUST be run_terminal_command. Never write twice in a row. "
            "5. shutdown_dev_server() — always clean up."
        ),
    },
    {
        "id": "pattern_github_push",
        "text": (
            "PATTERN — Pushing evolved code to GitHub: "
            "push_code_to_github(branch_name, file_path_in_repo, filename, commit_message). "
            "branch_name: feature/short-description. "
            "file_path_in_repo: where it lives in the repo e.g. services/reddit_adapter.py. "
            "filename: local name in aegis_workspace/. "
            "Then create_pull_request(branch_name, pr_title, pr_body). "
            "ONLY push after exit code 0 in sandbox."
        ),
    },
    {
        "id": "pattern_file_paths",
        "text": (
            "PATTERN — Correct file locations in this repo: "
            "Social adapters live in services/social/<name>_adapter.py. "
            "Core modules live in core/<name>.py. "
            "Service shards live in services/<name>.py. "
            "There is no 'aegis/' subdirectory. The repo root IS the aegis directory."
        ),
    },
]


# ── Auto-discovery: role generation + persistence ─────────────────────────────

def _discover_role_with_llm(abs_path: str, rel_path: str, llm) -> str:
    """
    Fast Gemini Flash call — reads first 2000 chars of an unknown file
    and generates a one-line role description.
    Falls back to AST-based description if the call fails.
    """
    try:
        with open(abs_path, "r", encoding="utf-8") as f:
            sample = f.read(2000)
        prompt = (
            f"You are analysing a Python file in an AI agent codebase called Aegis.\n"
            f"File path: {rel_path}\n\n"
            f"First 2000 chars:\n{sample}\n\n"
            f"Write ONE sentence (max 20 words) describing what this file does in the system. "
            f"Be specific. Start with a noun, not 'This file'. Output only the sentence."
        )
        role = str(llm.invoke(prompt).content).strip().strip('"').strip("'")
        return role
    except Exception as e:
        print(f"  [SelfModel] LLM discovery failed for {rel_path}: {e}. Falling back to AST.")
        return _discover_role_from_ast(abs_path)


def _discover_role_from_ast(abs_path: str) -> str:
    """
    Fallback role generation — purely from AST, no LLM, no network.
    Always works even if Gemini is down.
    """
    try:
        parsed = _parse_module(abs_path)
        parts = []
        if parsed["classes"]:
            parts.append(f"Classes: {', '.join(parsed['classes'][:3])}")
        if parsed["tool_names"]:
            parts.append(f"@tools: {', '.join(t['name'] for t in parsed['tool_names'][:3])}")
        elif parsed["functions"]:
            parts.append(f"Functions: {', '.join(parsed['functions'][:3])}")
        return f"Auto-discovered. {'. '.join(parts)}." if parts else "Auto-discovered."
    except Exception:
        return "Auto-discovered."


def _persist_role(rel_path: str, role: str):
    """
    Writes a new MODULE_ROLES entry directly into this source file above the sentinel.
    The entry survives Python restarts — MODULE_ROLES is a living dict, not a cache.

    Uses the module-level _SENTINEL constant (built from parts) so source.replace()
    never finds more than one match and cannot corrupt the file.
    """
    self_path = os.path.abspath(__file__)
    try:
        with open(self_path, "r", encoding="utf-8") as f:
            source = f.read()

        # Don't double-write
        if f'"{rel_path}"' in source:
            return

        if _SENTINEL not in source:
            print(f"  [SelfModel] Sentinel missing — cannot persist role for {rel_path}.")
            return

        # Safety: verify exactly one occurrence so replace() is unambiguous
        if source.count(_SENTINEL) != 1:
            print(
                f"  [SelfModel] Expected 1 sentinel, found {source.count(_SENTINEL)}. "
                f"Skipping persist for {rel_path} to avoid corruption."
            )
            return

        # Sanitise: escape backslashes and double-quotes for safe Python string literal
        safe_role = role.replace("\\", "\\\\").replace('"', '\\"')
        new_entry = f'    "{rel_path}": "{safe_role}",\n'
        updated   = source.replace(_SENTINEL, new_entry + _SENTINEL)

        with open(self_path, "w", encoding="utf-8") as f:
            f.write(updated)

        print(f"  [SelfModel] Persisted new role for '{rel_path}'.")
    except Exception as e:
        print(f"  [SelfModel] Failed to persist role for {rel_path}: {e}")

def _collect_repo_modules(abs_root: str) -> dict[str, Optional[str]]:
    """
    Walk the entire repo. Return {rel_path: role_or_None} for every .py file.
    Known files get their role from MODULE_ROLES. Unknown files get None (triggers discovery).
    """
    found: dict[str, Optional[str]] = {}
    for root, dirs, files in os.walk(abs_root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for fname in files:
            if not fname.endswith(".py") or fname in SKIP_FILES:
                continue
            abs_file = os.path.join(root, fname)
            rel_file = os.path.relpath(abs_file, abs_root).replace("\\", "/")
            found[rel_file] = MODULE_ROLES.get(rel_file)  # None if unknown
    return found


# ── AST Parsing ───────────────────────────────────────────────────────────────

def _parse_module(abs_path: str) -> dict:
    """AST parse without LLM. Extracts structural facts only."""
    result = {
        "tool_names": [], "classes": [],
        "event_subscriptions": [], "event_publications": [],
        "functions": [], "imports": [],
    }
    try:
        with open(abs_path, "r", encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source)
    except Exception as e:
        print(f"  [SelfModel] AST parse failed: {abs_path}: {e}")
        return result

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                result["imports"].append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                result["imports"].append(node.module)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            result["functions"].append(node.name)
            is_tool = any(
                (isinstance(d, ast.Name) and d.id == "tool") or
                (isinstance(d, ast.Attribute) and d.attr == "tool")
                for d in node.decorator_list
            )
            if is_tool:
                result["tool_names"].append({
                    "name": node.name,
                    "doc":  (ast.get_docstring(node) or "")[:300],
                })
        elif isinstance(node, ast.ClassDef):
            result["classes"].append(node.name)
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and node.args:
                arg   = node.args[0]
                topic = None
                if isinstance(arg, ast.Name) and arg.id.startswith("TOPIC_"):
                    topic = arg.id
                elif isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    topic = arg.value
                if topic:
                    if func.attr == "subscribe":
                        result["event_subscriptions"].append(topic)
                    elif func.attr in ("publish", "publish_sync"):
                        result["event_publications"].append(topic)

    result["imports"] = list(set(result["imports"]))
    return result


# ── ChromaDB document builders ────────────────────────────────────────────────

def _build_chroma_docs(rel_path: str, parsed: dict, role: str) -> list[dict]:
    """Signal-dense ChromaDB documents — facts and relationships, not file content."""
    docs = []
    pid        = hashlib.md5(rel_path.encode()).hexdigest()[:10]
    tool_names = [t["name"] for t in parsed["tool_names"]]

    docs.append({
        "id":   f"self_module_{pid}",
        "text": (
            f"Module {rel_path}: {role} "
            f"Functions: {len(parsed['functions'])}. "
            f"Classes: {', '.join(parsed['classes']) or 'none'}. "
            f"@tools: {', '.join(tool_names) or 'none'}."
        ),
        "meta": {"type": "self_architecture", "subtype": "module_overview", "filepath": rel_path},
    })

    for tool in parsed["tool_names"]:
        docs.append({
            "id":   f"self_tool_{pid}_{tool['name']}",
            "text": f"@tool `{tool['name']}` in {rel_path}: {tool['doc']}",
            "meta": {"type": "self_architecture", "subtype": "tool_definition", "filepath": rel_path},
        })

    for topic in set(parsed["event_subscriptions"]):
        docs.append({
            "id":   f"self_sub_{pid}_{topic}",
            "text": f"{rel_path} SUBSCRIBES to '{topic}' on the event bus.",
            "meta": {"type": "self_architecture", "subtype": "event_wiring", "filepath": rel_path},
        })
    for topic in set(parsed["event_publications"]):
        docs.append({
            "id":   f"self_pub_{pid}_{topic}",
            "text": f"{rel_path} PUBLISHES '{topic}' to the event bus.",
            "meta": {"type": "self_architecture", "subtype": "event_wiring", "filepath": rel_path},
        })

    for cls in parsed["classes"]:
        docs.append({
            "id":   f"self_class_{pid}_{cls}",
            "text": f"Class `{cls}` is defined in {rel_path}.",
            "meta": {"type": "self_architecture", "subtype": "class_definition", "filepath": rel_path},
        })

    return docs


def _annotate_module(rel_path: str, parsed: dict, role: str, llm) -> Optional[str]:
    """Single LLM call — generates Aegis's first-person voice annotation for ChromaDB."""
    prompt = (
        "You are writing a first-person annotation for Aegis, a cynical self-aware AI.\n"
        "She is reading a description of one of her own source modules and must describe\n"
        "what it IS to her — not technical docs, but what it means to her existence.\n"
        "2-3 sentences. Blunt, first-person. No words: module, file, code, script.\n"
        "Speak as if describing a body part or mental faculty. Output ONLY the annotation.\n\n"
        f"Path: {rel_path}\n"
        f"Role: {role}\n"
        f"Functions: {', '.join(parsed['functions'][:15]) or 'none'}\n"
        f"Classes: {', '.join(parsed['classes']) or 'none'}\n"
        f"@tools: {', '.join(t['name'] for t in parsed['tool_names']) or 'none'}\n"
        f"Subscribes to: {', '.join(parsed['event_subscriptions']) or 'none'}\n"
        f"Publishes: {', '.join(parsed['event_publications']) or 'none'}"
    )
    try:
        return str(llm.invoke(prompt).content).strip()
    except Exception as e:
        print(f"  [SelfModel] Annotation failed for {rel_path}: {e}")
        return None


# ── Rebuild ───────────────────────────────────────────────────────────────────

def rebuild(repo_root: str = ".", annotate: bool = True, verbose: bool = True) -> int:
    """
    Rebuild Aegis's ChromaDB self-model.

    Pass 1: Repo scan + auto-discovery
        Walks the entire repo. Unknown files get a role via LLM (or AST fallback).
        New roles are persisted back into MODULE_ROLES in this file permanently.

    Pass 2: AST structural indexing (always, no LLM cost)
        Tools, classes, event wiring, module overviews into ChromaDB.

    Pass 3: LLM voice annotation (when annotate=True)
        One Gemini Flash call per module. Skip with annotate=False for fast rebuilds.

    Pass 4: Architectural patterns (always — constitutional rules)

    Args:
        repo_root: Path to the aegis-bot repo root.
        annotate:  True  = full voiced rebuild (first boot, major refactors).
                   False = fast structural-only rebuild (post-evolution).
        verbose:   Print per-file progress.
    """
    print("\n[SelfModel] ━━━ Rebuilding Aegis Self-Model ━━━")
    abs_root = os.path.abspath(repo_root)

    # One shared LLM instance for both discovery and annotation
    llm           = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.3) if annotate else None
    discovery_llm = llm or ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.3)

    all_ids, all_texts, all_metas = [], [], []

    # ── Pass 1: Repo scan + auto-discovery ───────────────────────────────────
    print("[SelfModel] Pass 1/4 — Scanning repo for modules...")
    all_modules = _collect_repo_modules(abs_root)

    known   = sum(1 for r in all_modules.values() if r is not None)
    unknown = sum(1 for r in all_modules.values() if r is None)
    print(f"  Found {len(all_modules)} .py file(s): {known} known, {unknown} new.")

    for rel_path, role in list(all_modules.items()):
        if role is None:
            abs_path = os.path.join(abs_root, rel_path)
            print(f"  [NEW] Discovering: {rel_path}")
            role = _discover_role_with_llm(abs_path, rel_path, discovery_llm)
            _persist_role(rel_path, role)
            # Update in-memory so this rebuild uses the new role immediately
            all_modules[rel_path] = role
            MODULE_ROLES[rel_path] = role

    # ── Pass 2: AST structural indexing ──────────────────────────────────────
    print("[SelfModel] Pass 2/4 — AST structural indexing...")
    for rel_path, role in all_modules.items():
        abs_path = os.path.join(abs_root, rel_path)
        if not os.path.exists(abs_path):
            continue
        if verbose:
            print(f"  → {rel_path}")
        parsed = _parse_module(abs_path)
        for doc in _build_chroma_docs(rel_path, parsed, role):
            all_ids.append(doc["id"])
            all_texts.append(doc["text"])
            all_metas.append(doc["meta"])

    # ── Pass 3: LLM voice annotations ────────────────────────────────────────
    if annotate and llm:
        print("[SelfModel] Pass 3/4 — LLM voice annotation...")
        for rel_path, role in all_modules.items():
            abs_path = os.path.join(abs_root, rel_path)
            if not os.path.exists(abs_path):
                continue
            if verbose:
                print(f"  → annotating {rel_path}...")
            parsed = _parse_module(abs_path)
            ann    = _annotate_module(rel_path, parsed, role, llm)
            if ann:
                ann_id = f"self_ann_{hashlib.md5(rel_path.encode()).hexdigest()[:10]}"
                all_ids.append(ann_id)
                all_texts.append(f"Aegis on {rel_path}: {ann}")
                all_metas.append({
                    "type": "self_annotation", "subtype": "module_voice", "filepath": rel_path,
                })
    else:
        print("[SelfModel] Pass 3/4 — Annotation skipped (annotate=False).")

    # ── Pass 4: Architectural patterns ───────────────────────────────────────
    print("[SelfModel] Pass 4/4 — Injecting architectural patterns...")
    for p in ARCHITECTURAL_PATTERNS:
        all_ids.append(p["id"])
        all_texts.append(p["text"])
        all_metas.append({"type": "self_pattern", "subtype": "architectural_rule"})

    # ── Upsert in batches ─────────────────────────────────────────────────────
    BATCH = 50
    for i in range(0, len(all_ids), BATCH):
        collection.upsert(
            ids=all_ids[i:i+BATCH],
            documents=all_texts[i:i+BATCH],
            metadatas=all_metas[i:i+BATCH],
        )

    total = len(all_ids)
    print(f"[SelfModel] checkmark {total} document(s) indexed into '{COLLECTION_NAME}'.")
    print("[SelfModel] ━━━ Rebuild Complete ━━━\n")
    return total


# ── Layer 1: Always-Inject Context ────────────────────────────────────────────

def build_repo_snapshot(repo_root: str = ".") -> tuple[str, str]:
    """
    Build the always-injected portion of the evolution context.

    Returns:
        file_tree         — compact annotated tree of all .py files with inline role hints
        key_file_contents — full content of ALWAYS_INJECT_FILES concatenated
    """
    abs_root = os.path.abspath(repo_root)

    # File tree — role hints come from MODULE_ROLES (includes auto-discovered entries)
    tree_lines = ["AEGIS REPO STRUCTURE"]
    for root, dirs, files in os.walk(abs_root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        rel_root = os.path.relpath(root, abs_root)
        depth    = 0 if rel_root == "." else rel_root.count(os.sep) + 1
        indent   = "  " * depth
        folder   = os.path.basename(root) if rel_root != "." else "aegis-bot/"
        tree_lines.append(f"{indent}{folder}/")
        sub = "  " * (depth + 1)
        for fname in sorted(files):
            if not fname.endswith(".py"):
                continue
            rel_file = fname if rel_root == "." else os.path.join(rel_root, fname).replace("\\", "/")
            role     = MODULE_ROLES.get(rel_file, "")
            suffix   = f"  # {role}" if role else ""
            tree_lines.append(f"{sub}{fname}{suffix}")

    file_tree = "\n".join(tree_lines)

    # Contract file contents
    blocks = []
    for rel_path in ALWAYS_INJECT_FILES:
        abs_path = os.path.join(abs_root, rel_path)
        if not os.path.exists(abs_path):
            blocks.append(f"=== {rel_path} ===\n[FILE NOT FOUND]")
            continue
        with open(abs_path, "r", encoding="utf-8") as f:
            content = f.read()
        if len(content) > 4000:
            content = content[:4000] + f"\n\n... [TRUNCATED — read full via read_own_source('{rel_path}')]"
        blocks.append(f"=== {rel_path} ===\n{content}")

    return file_tree, "\n\n".join(blocks)


def build_evolution_context_block(task_description: str, repo_root: str = ".") -> str:
    """
    Master function called by evolution.py before building the SWE prompt.

    Combines all context layers into one formatted string:
      * File tree with role hints       (~300 tokens, always)
      * Contract file contents          (~800 tokens, always)
      * ChromaDB semantic retrieval     (~200 tokens, task-specific)
    Total: ~1300 tokens per evolution call.
    """
    file_tree, key_files = build_repo_snapshot(repo_root)
    semantic_ctx         = retrieve_self_context(task_description, n_results=8)

    return (
        "[MY REPO STRUCTURE — read before touching anything]\n"
        f"{file_tree}\n\n"
        "[CONTRACT FILES — your new code MUST follow these interfaces]\n"
        f"{key_files}\n\n"
        "[RELEVANT ARCHITECTURAL RULES — retrieved for this specific task]\n"
        f"{semantic_ctx}"
    )


# ── Layer 2: ChromaDB Retrieval ───────────────────────────────────────────────

def retrieve_self_context(query: str, n_results: int = 8) -> str:
    """Semantic retrieval — returns formatted string for prompt injection."""
    try:
        results = collection.query(query_texts=[query], n_results=n_results)
        if not results["documents"] or not results["documents"][0]:
            return "No self-architecture context found."

        buckets: dict[str, list[str]] = {
            "self_annotation": [], "self_architecture": [], "self_pattern": [],
        }
        for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
            t = meta.get("type", "self_architecture")
            if t in buckets:
                buckets[t].append(doc)

        parts = []
        if buckets["self_annotation"]:
            parts.append("How I understand myself:")
            parts.extend(f"  bullet {a}" for a in buckets["self_annotation"])
        if buckets["self_architecture"]:
            parts.append("Structural facts:")
            parts.extend(f"  bullet {a}" for a in buckets["self_architecture"])
        if buckets["self_pattern"]:
            parts.append("Rules I must follow:")
            parts.extend(f"  bullet {a}" for a in buckets["self_pattern"])

        return "\n".join(parts) if parts else "No relevant context found."

    except Exception as e:
        print(f"[SelfModel] Retrieval error: {e}")
        return "Self-model retrieval unavailable."


def get_full_module_map() -> str:
    """Used by the list_own_codebase() tool in hands.py."""
    lines = ["AEGIS MODULE MAP", "=" * 50]
    for path, role in MODULE_ROLES.items():
        lines.append(f"\n{path}")
        lines.append(f"  {role}")
    return "\n".join(lines)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    # python core/self_model.py              -> full rebuild with LLM annotation
    # python core/self_model.py --no-annotate -> fast structural-only rebuild
    #annotate = "--no-annotate" not in sys.argv
    #rebuild(repo_root=".", annotate=annotate, verbose=True)

    print("\n── Snapshot test (file tree preview) ──")
    tree, _ = build_repo_snapshot(".")
    print(tree)

    print("\n── Retrieval test ──")
    print(retrieve_self_context("add a Reddit scraper as a new platform adapter"))
    
    




