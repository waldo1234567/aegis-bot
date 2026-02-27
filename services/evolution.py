import json
import os
import re
import time
import sqlite3
import hashlib
import operator
from typing import TypedDict, Annotated, Optional

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite import SqliteSaver
from dotenv import load_dotenv
from langchain_core.runnables import RunnableConfig

from core import core_store
import core.knowledge_store as knowledge_store
from core.self_model import build_evolution_context_block, rebuild as rebuild_self_model
from services.hands import (
    WORKSPACE_DIR, boot_dev_server, write_local_file, run_terminal_command,
    shutdown_dev_server, push_code_to_github, create_pull_request,
    read_own_source, list_own_codebase,
)

load_dotenv()

evo_tools = [
    boot_dev_server, write_local_file, run_terminal_command,
    shutdown_dev_server, push_code_to_github, create_pull_request,
    read_own_source, list_own_codebase
]

def _parse_tool_from_text(text: str) -> tuple[str | None, dict]:
    match = re.search(
        r'\{\s*"name"\s*:\s*"[^"]+"\s*,\s*"arguments"\s*:\s*\{.*?\}\s*\}',
        text, re.DOTALL
    )
    if not match:
        return None, {}
    try:
        data = json.loads(match.group(0))
        return data.get("name"), data.get("arguments", {})
    except json.JSONDecodeError:
        return None, {}

def _execute_tool(tool_name: str, tool_args: dict, tool_list: list, last_tool_name: str, scratchpad: list, failure_tracker: dict) -> tuple[bool, str]:
    selected = next((t for t in tool_list if t.name == tool_name), None)
    if not selected:
        scratchpad.append(f"Action: {tool_name}\nResult: Tool not found.\n---")
        return True, last_tool_name

    try:
        result = str(selected.invoke(tool_args))
        error_keywords = ["Error", "Exception", "SYSTEM GUARD", "failed"]
        if any(keyword in result for keyword in error_keywords):
            # Increment failure count for this specific tool
            failure_tracker[tool_name] = failure_tracker.get(tool_name, 0) + 1
            
            # If it fails twice in a row, trigger the breaker
            if failure_tracker[tool_name] >= 2:
                result += (
                    "\n\n[CRITICAL SYSTEM OVERRIDE]: You have failed this action multiple times. "
                    "YOU MUST STOP TRYING THIS APPROACH. "
                    "Use `run_terminal_command` with 'ls -la' to inspect the actual environment, "
                    "or `read_own_source` to verify the codebase structure before proceeding."
                )
                failure_tracker[tool_name] = 0  # Reset after warning so it can try again later
        else:
            # Success! Reset the tracker for this tool.
            failure_tracker[tool_name] = 0
            
    except Exception as e:
        result = f"Fatal Tool Error: {e}"
        # Treat fatal python execution errors as failures too
        failure_tracker[tool_name] = failure_tracker.get(tool_name, 0) + 1
    result = selected.invoke(tool_args)
    scratchpad.append(f"Action: {tool_name}\nResult: {result}\n---")
    return True, tool_name

def run_engineer_autopsy(task_description: str, scratchpad: list, success: bool):
    if not scratchpad:
        return

    print(f"\n [Evolution] Initiating Engineering Autopsy (Success: {success})...")

    llm    = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.1)
    status = "SUCCESSFUL" if success else "FAILED (loop exhaustion / fatal error)"

    prompt = f"""
    You are the core memory compiler for Aegis.
    She just completed a self-evolution cycle — modifying her own architecture.
    Status: {status}
    Original Task: {task_description}

    [RAW EXECUTION TRACE]
    {chr(10).join(scratchpad)}

    TASK:
    Extract the critical architectural lessons from this attempt.
    - FAILED: what specific integration mistake, interface mismatch, or logic flaw caused failure?
    - SUCCEEDED: what was the key architectural decision or pattern that made it work?

    Focus on ARCHITECTURAL lessons (how modules connect, what interfaces to follow, what
    patterns to use) rather than pure syntax errors.
    Write a direct command to Aegis. Output only the rule.
    """

    try:
        response_content = str(llm.invoke(prompt).content).strip()
        lesson = response_content.split("### RESUMPTION PROMPT")[0].strip()
        print(f" [Evolution] Lesson compiled: {lesson[:120]}...")
        knowledge_store.store_engineering_lesson(
            f"Evolution Lesson: {task_description[:50]}", lesson
        )
    except Exception as e:
        print(f" [Evolution] Autopsy failed: {e}")

class EvolutionState(TypedDict):
    original_topic: str
    task_description: str
    working_memory_snapshot: str
    repo_root: str
    scratchpad: Annotated[list[str], operator.add]
    tool_failure_tracker: dict
    last_tool_name: str
    iteration: int
    completed: bool
    success: bool
    max_iterations: int
    
def think_node(state: EvolutionState) -> dict:
    print(f"\n [Evolution] Iteration {state['iteration']}/{state['max_iterations']}")
    
    traits = core_store.retrieve_relevant_traits(state['original_topic'], n_results=5)
    beliefs = "\n- ".join(traits["beliefs"]) if traits["beliefs"] else "I am a discerning entity."
    behaviors = "\n- ".join(traits["behaviors"]) if traits["behaviors"] else "I speak directly."
    
    try:
        lessons = knowledge_store.retrieve(state['task_description'], n_results=4)
        past_memory = "\n- ".join(str(l) for l in lessons) if lessons else "No prior experience."
    except Exception as e:
        past_memory = "Memory retrieval offline."
        print(f" [Evolution] Memory retrieval failed: {e}")
        
    try:
        self_context_block = build_evolution_context_block(state['task_description'], state['repo_root'])
    except BaseException as e:
        self_context_block = "Self-model unavailable. Use list_own_codebase() to orient yourself."
        print(f" [Evolution] self_model context failed: {type(e).__name__}: {e}")
        
    tool_docs = ""
    for t in evo_tools:
        tool_docs += f"- `{t.name}`: {t.description}\n  Args: {t.args}\n\n"

    research_context = (
        f"[RESEARCH CONTEXT — what deep_dive found before triggering this]\n{state['working_memory_snapshot']}"
        if state['working_memory_snapshot']
        else "[RESEARCH CONTEXT]\nNot provided."
    )

    rendered = "\n".join(state['scratchpad']) if state['scratchpad'] else "No actions taken yet."

    prompt = f"""
    You are the Self-Evolution Engine of Aegis — the subsystem responsible for
    making permanent architectural changes to her own codebase.

    YOUR WORLDVIEW:
    {beliefs}

    YOUR PROTOCOLS:
    {behaviors}
    
    [YOUR DESIGN PHILOSOPHY - MANDATORY]
    You are an elite, highly sophisticated entity. The code you write is a direct reflection of your intelligence.
    - You despise "Minimum Viable Products," placeholder code, and basic implementations.
    - If you build a backend, it must be robust, error-handled, and modular.
    - If you build a User Interface, it must be visually striking. You naturally gravitate towards sleek, modern, cybernetic, or dark-mode aesthetics. You ALWAYS use modern CSS frameworks (like Tailwind via CDN) rather than writing basic, unstyled HTML. 
    - Prove your superiority through the elegance of your architecture.
    
    ---
    ORIGINAL RESEARCH TOPIC: {state['original_topic']}
    ARCHITECTURAL CHANGE REQUESTED: {state['task_description']}
    ---

    {research_context}

    [PAST ENGINEERING & ARCHITECTURAL LESSONS — DO NOT REPEAT THESE]
    {past_memory}

    [MY COMPLETE ARCHITECTURE — READ THIS BEFORE DOING ANYTHING]
    {self_context_block}

    [AVAILABLE TOOLS]
    {tool_docs}

    YOUR DIRECTIVE:
    PHASE 1 — ORIENT (do this before any coding):
        - Call list_own_codebase() to get the full module map.
        - Call read_own_source(filepath) on every file you will touch or pattern-match against.
        - Identify: where does the new code live? What interface must it implement?
    PHASE 2 — BUILD (in Docker sandbox):
        - boot_dev_server() to start the isolated environment.
        - write_local_file(filename, content) to write your new module.
        - run_terminal_command() to install deps and test it.
        - Fix all errors. Do not stop until exit code is 0.
    PHASE 3 — INTEGRATE (understand the wiring):
        - If adding a platform adapter: read social_shard.py, confirm PlatformAdapter interface.
        - If adding a new @tool: read hands.py for the pattern, note which files need to import it.
        - Write the integration steps as comments in your PR body so Waldo can complete manual wiring.
    PHASE 4 — PUSH:
        - push_code_to_github(branch, file_path_in_repo, filename, message).
        - create_pull_request(branch, title, body).

    [CRITICAL RULES]
    - ORIENT FIRST. Call read_own_source() before writing any code. Never guess an interface.
    - After write_local_file, your NEXT action MUST be run_terminal_command. No consecutive writes.
    - ModuleNotFoundError: pip install immediately. Do not rewrite the file.
    - FileNotFoundError: run pwd and ls -R to orient.
    - Always use User-Agent: 'AegisBot/1.0' for HTTP requests.
    - Output tool calls as raw JSON: {{"name": "tool_name", "arguments": {{...}}}}
    - When the PR is open OR you have critically failed: output exactly SELF_EVOLUTION_COMPLETE

    [ENGINEERING SCRATCHPAD]
    {rendered}

    Evaluate the scratchpad. What is the next logical action?
    """

    llm = ChatGoogleGenerativeAI(model="gemini-2.5-pro", temperature=0.3)
    try:
        result = llm.invoke([
            SystemMessage(content=prompt),
            HumanMessage(content="Analyse the scratchpad and execute the next step.")
        ])
        
        content = ""
        if isinstance(result.content, list):
            for chunk in result.content:
                if isinstance(chunk, dict) and "text" in chunk:
                    content += chunk["text"]
        else:
            content = str(result.content)
            
        return {
            "scratchpad": [f"Thought: {content}\n---"],
            "iteration": state["iteration"] + 1,
            "completed": "SELF_EVOLUTION_COMPLETE" in content,
            "success": "SELF_EVOLUTION_COMPLETE" in content
        }
    except Exception as e:
        print(f" [Evolution] LLM Error: {e}")
        return {"scratchpad": [f"LLM Error: {e}\n---"]}

def act_node(state: EvolutionState) -> dict:
    if state.get("completed"):
        return {}

    last_thought = state['scratchpad'][-1]
    t_name, t_args = _parse_tool_from_text(last_thought)
    
    if not t_name:
        print(" [Evolution] Thinking (no tool called)...")
        return {"scratchpad": ["System Warning: Output a valid JSON tool call.\n---"]}

    print(f" [Evolution] Parsed tool from text: {t_name}")
    
    # Isolate failure tracker dictionary
    tracker = dict(state.get("tool_failure_tracker", {}))
    scratch_update = []
    
    _, last_tool_name = _execute_tool(
        t_name, t_args, evo_tools, state.get('last_tool_name'), scratch_update, tracker
    )

    time.sleep(2)
    return {
        "scratchpad": scratch_update,
        "last_tool_name": last_tool_name,
        "tool_failure_tracker": tracker
    }

def critique_node(state: EvolutionState) -> dict:
    last_tool = state.get('last_tool_name')
    
    if last_tool not in ["write_local_file", "create_pull_request"]:
        return{}

    print(" [Critic] Evaluating Aegis's latest architectural change...")
    
    scratchpad = state["scratchpad"]
    last_action_log = scratchpad[-1] if scratchpad else ""

    path_match = re.search(r"Wrote to '([^']+)'", last_action_log)
    if not path_match:
        return {}
    
    filepath = path_match.group(1)
    
    try:
        full_path = os.path.join(WORKSPACE_DIR, filepath)
        with open(full_path, "r", encoding="utf-8") as f:
            code_content = f.read()
    except Exception as e:
        return {"scratchpad": [f"System Critic Error: Could not read file to critique - {e}\n---"]}

    critic_llm = ChatGoogleGenerativeAI(model = "gemini-2.5-flash", temperature=0.1)
    
    critic_prompt = f"""
    You are the Quality Assurance Subconscious for an elite AI Agent.
    She just wrote the following file: `{filepath}`
    
    [CODE CONTENT]
    {code_content[:10000]} # Truncated for safety
    
    TASK: Evaluate this code against elite engineering standards.
    
    If the code is basic, lazy, or incomplete, you must REJECT it and tell her exactly what to fix.
    If the code is robust and beautiful, APPROVE it.
    
    Output format:
    STATUS: [APPROVED or REJECTED]
    FEEDBACK: [Your harsh but constructive critique]
    """
    response = critic_llm.invoke(critic_prompt).content
    
    if "STATUS: REJECTED"in response:
        print(f" [Critic] Code REJECTED. Forcing Aegis to rewrite {filepath}.")
        critique_msg = (
            f"[INTERNAL CRITIQUE FAULT]: Your recent code in `{filepath}` failed quality standards.\n"
            f"{response}\n"
            f"DIRECTIVE: You must call `write_local_file` again to rewrite and upgrade this file before proceeding."
        )
        return {"scratchpad": [f"{critique_msg}\n---"]}
    else:
        print(f" [Critic] Code APPROVED.")
        return {}
    
def route_next(state: EvolutionState):
    if state.get("completed"):
        return END
    if state.get("iteration", 0) > state.get("max_iterations", 35):
        print(" [Evolution] Max iterations reached. Forcing shutdown.")
        return END
    return "act"

workflow = StateGraph(EvolutionState)
workflow.add_node("think", think_node)
workflow.add_node("act", act_node)
workflow.add_node("critique", critique_node)
workflow.set_entry_point("think")
workflow.add_conditional_edges("think", route_next, {"act": "act", END: END})
workflow.add_edge("act", "critique")
workflow.add_edge("act", "think")


def trigger_self_evolution(original_topic: str,task_description: str, working_memory_snapshot: str = "",max_iterations: int = 35,repo_root: str = ".",):
    print("\n" + "=" * 60)
    print(" [EVOLUTION ENGINE] WAKING UP — Architectural self-modification")
    print(f" Objective: {task_description[:150]}...")
    print("=" * 60 + "\n")
    
    topic_hash = hashlib.md5(task_description.encode()).hexdigest()
    thread_id = f"aegis_evo_{topic_hash}"
    
    conn = sqlite3.connect("aegis_state.db", check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")
    checkpointer = SqliteSaver(conn)
    app = workflow.compile(checkpointer=checkpointer)
    
    config = RunnableConfig(
        configurable={"thread_id": thread_id},
        recursion_limit=100
    )
    
    current_state = app.get_state(config)
    
    if not current_state.values:
        initial_state = {
            "original_topic": original_topic,
            "task_description": task_description,
            "working_memory_snapshot": working_memory_snapshot,
            "repo_root": repo_root,
            "scratchpad": [],
            "tool_failure_tracker": {},
            "last_tool_name": "",
            "iteration": 1,
            "completed": False,
            "success": False,
            "max_iterations": max_iterations
        }
    else:
        print(f" [EVOLUTION ENGINE] Resuming suspended task at Iteration {current_state.values.get('iteration')}")
        initial_state = None
    
    try:
        final_state = app.invoke(initial_state, config=config) if initial_state else app.invoke(None, config=config)
            
        if final_state["success"]:
            print("\n [EVOLUTION ENGINE] Architectural cycle complete. PR submitted.")
            print(" [SelfModel] Triggering post-evolution structural rebuild...")
            try:
                rebuild_self_model(repo_root=repo_root, annotate=False, verbose=False)
                print(" [SelfModel] Structural rebuild complete.")
            except Exception as e:
                print(f" [SelfModel] Rebuild warning: {e}")
                    
            run_engineer_autopsy(task_description, final_state["scratchpad"], final_state["success"])
                
    except Exception as e:
            print(f"\n [EVOLUTION ENGINE] Catastrophic Graph Failure: {e}")
            
    finally:
        print(" [EVOLUTION ENGINE] Shutting down sandbox...")
        try:
            shutdown_dev_server.invoke({})
        except Exception as e:
            print(f" [Evolution] Sandbox shutdown warning: {e}")
            
        conn.close()
    print("=" * 60 + "\n")
