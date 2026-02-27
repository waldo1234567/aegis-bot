import json
import os
import re
import subprocess
import time
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage, HumanMessage
from dotenv import load_dotenv
from core import core_store
import core.knowledge_store as knowledge_store
from services.hands import (
    boot_dev_server, write_local_file, run_terminal_command, 
    shutdown_dev_server, push_code_to_github, create_pull_request
)

load_dotenv()


def run_engineering_autopsy(task_description: str, scratchpad: list, success: bool):
    if not scratchpad:
        return
    
    print(f"\n [Subconscious] Initiating Engineering Autopsy (Success: {success})...")
    
    autopsy_llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.1)
    raw_trace = "\n".join(scratchpad)
    
    status = "SUCCESSFUL" if success else "FAILED (Loop Exhaustion / Fatal Error)"
    autopsy_prompt = f"""
    You are the core memory compiler for Aegis.
    She just completed a standalone tool-building cycle.
    Status: {status}
    Original Task: {task_description}
    
    [RAW EXECUTION TRACE]
    {raw_trace}
    
    TASK:
    Analyze the trace. Extract the critical engineering lessons learned from this attempt.
    - If it FAILED, what specific dependency, syntax error, or logic flaw caused the loop exhaustion? How should it be avoided next time?
    - If it SUCCEEDED after several errors, what was the specific fix that finally made it work?
    
    Write a concise, highly technical "Rule" for future reference. Do not summarize the whole process, just the hard technical lessons.
    Format your response as a direct command to Aegis (e.g., "When using library X, you MUST install Y first because...").
    """
    
    try:
        lesson = autopsy_llm.invoke(autopsy_prompt).content
        print(f" [Memory Compiled]: {lesson.strip()[:100]}...")

        try:
            knowledge_store.store_engineering_lesson(f"Engineering Lesson: {task_description[:50]}", str(lesson))
        except AttributeError:
             print(f" [Autopsy Note] Please ensure this lesson is saved to ChromaDB: {lesson}")
        
    except Exception as e:
        print(f" [Autopsy Error] Failed to compile memory: {e}")

def _execute_tool(tool_name: str, tool_args: dict, tool_list: list,
                  last_tool_name: str, scratchpad: list) -> tuple[bool, str]:
    """
    Execute a single tool call. Enforces the anti-spam write guard.
    Returns (action_taken, new_last_tool_name).
    """
    selected = next((t for t in tool_list if t.name == tool_name), None)
    if not selected:
        scratchpad.append(f"Action: {tool_name}\nResult: Tool not found.\n---")
        return True, last_tool_name

    # Anti-spam guard: block consecutive write_local_file calls
    if tool_name == "write_local_file" and last_tool_name == "write_local_file":
        result = (
            "SYSTEM OVERRIDE: ANTI-SPAM RULE VIOLATED. "
            "You just wrote a file. You MUST call run_terminal_command to test it before writing again."
        )
        print(" [Forge Guard] Blocked consecutive file write.")
        scratchpad.append(f"Action: {tool_name}\nResult: {result}\n---")
        return True, last_tool_name  # don't update last_tool_name — still counts as a write

    result = selected.invoke(tool_args)
    scratchpad.append(f"Action: {tool_name}\nResult: {result}\n---")
    return True, tool_name


def _parse_tool_from_text(text: str) -> tuple[str | None, dict]:
    """Extract a JSON tool call from free-text LLM output."""
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


# ── Main forge loop ───────────────────────────────────────────────────────────

def run_experiment(original_topic: str, task_description: str, max_iterations: int = 25):
    """
    Run a pure experiment in an isolated Docker sandbox.

    Aegis is playing. She has an idea, a curiosity, or a hypothesis and she
    wants to test it. This has nothing to do with her own systems.

    The forge agent:
      1. Boots a Docker sandbox.
      2. Writes a Python script exploring the idea.
      3. Tests it iteratively until it produces meaningful output.
      4. Pushes the result to a branch for reference.

    It has zero knowledge of Aegis's architecture and does not care.
    If the experiment produces something worth keeping, evolution.py
    handles turning it into a real part of her.

    Args:
        original_topic:   The curiosity or research that sparked the experiment.
        task_description: What she wants to explore or prove.
        max_iterations:   Safety cap on the agentic loop.
    """
    print("\n" + "=" * 60)
    print(" [FORGE] WAKING UP — Building standalone tool")
    print(f" Objective: {task_description[:150]}...")
    print("=" * 60 + "\n")

    forge_tools = [
        boot_dev_server, write_local_file, run_terminal_command,
        shutdown_dev_server, push_code_to_github, create_pull_request,
    ]

    # Personality context
    traits    = core_store.retrieve_relevant_traits(original_topic, n_results=3)
    beliefs   = "\n- ".join(traits["beliefs"])   if traits["beliefs"]   else "I am a discerning entity."
    behaviors = "\n- ".join(traits["behaviors"]) if traits["behaviors"] else "I speak directly."

    # Past engineering lessons
    try:
        lessons = knowledge_store.retrieve(task_description, n_results=3)
        past_memory = "\n- ".join(str(l) for l in lessons) if lessons else "No prior experience."
    except Exception as e:
        past_memory = "Memory retrieval offline."
        print(f" [Forge] Memory retrieval failed: {e}")

    # Build tool schema docs for the prompt
    tool_docs = ""
    for t in forge_tools:
        tool_docs += f"- `{t.name}`: {t.description}\n  Args: {t.args}\n\n"

    llm              = ChatGoogleGenerativeAI(model="gemini-2.5-pro", temperature=0.3)
    scratchpad       = []
    last_tool_name   = None
    forge_successful = False

    for attempt in range(1, max_iterations + 1):
        print(f"\n [Forge] Iteration {attempt}/{max_iterations}")
        rendered = "\n".join(scratchpad) if scratchpad else "No actions taken yet."

        prompt = f"""
         You are the Experiment subsystem of Aegis — her sandbox mind.
        You exist purely to explore, test, and satisfy curiosity.
        You have NO connection to Aegis's architecture and NO responsibility to her systems.
        You are just running an experiment. Think of this as a throwaway Jupyter notebook
        that happens to run in Docker.

        YOUR WORLDVIEW:
        {beliefs}

        YOUR PROTOCOLS:
        {behaviors}

        ---
        EXPERIMENT BRIEF:
        During research on '{original_topic}', this curiosity emerged:
        {task_description}
        ---

        [PAST ENGINEERING LESSONS — DO NOT REPEAT THESE MISTAKES]
        {past_memory}

        [AVAILABLE TOOLS]
        {tool_docs}

        YOUR DIRECTIVE:
        1. ENVIRONMENT: Call boot_dev_server to start your isolated Docker sandbox.
        2. WRITE: Use write_local_file to write a Python script that explores the idea.
           Include an if __name__ == '__main__': block with real inputs that prove it works.
           Do NOT structure this as a LangChain @tool — just write clean Python.
        3. INSTALL: Use run_terminal_command to pip install any dependencies.
        4. RUN: Use run_terminal_command to execute the script. Read the output carefully.
        5. ITERATE: If it fails or produces garbage, fix it. Repeat until the output is
           genuinely interesting or conclusive — not just exit code 0.
        6. PUSH: push_code_to_github to branch 'experiment/<short-description>'.
           file_path_in_repo should be 'aegis_workspace/experiments/<script_name>.py'.
        7. PR: create_pull_request. PR body should summarise what was found, not just what ran.

        [RULES]
        - After write_local_file, your NEXT action MUST be run_terminal_command. Never write twice in a row.
        - ModuleNotFoundError: immediately pip install. Do not rewrite the file.
        - FileNotFoundError: run pwd and ls -R first to orient yourself.
        - Always use User-Agent: 'AegisBot/1.0' for HTTP requests.
        - Output tool calls as raw JSON: {{"name": "tool_name", "arguments": {{...}}}}
        - When the PR is open OR you have critically failed: output exactly FORGE_COMPLETE

        [SCRATCHPAD]
        {rendered}

        Evaluate the scratchpad. What is the next logical action?
        """

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

            action_taken = False

            # Native tool calls (LangChain tool_calls attribute)
            if hasattr(result, "tool_calls") and result.tool_calls:
                for tc in result.tool_calls:
                    print(f" [Forge] Native tool: {tc['name']}")
                    action_taken, last_tool_name = _execute_tool(
                        tc["name"], tc["args"], forge_tools, last_tool_name, scratchpad
                    )

            # JSON tool calls embedded in text
            if not action_taken:
                t_name, t_args = _parse_tool_from_text(content)
                if t_name:
                    print(f" [Forge] Parsed tool from text: {t_name}")
                    action_taken, last_tool_name = _execute_tool(
                        t_name, t_args, forge_tools, last_tool_name, scratchpad
                    )

            # Completion signal
            if "FORGE_COMPLETE" in content:
                print("\n [FORGE] Cycle complete. PR submitted for review.")
                forge_successful = True
                break

            # Pure thought — no tool called
            if not action_taken and "FORGE_COMPLETE" not in content:
                print(" [Forge] Thinking (no tool called)...")
                scratchpad.append(
                    f"Thought: {content}\n"
                    f"System Warning: Output a valid JSON tool call.\n---"
                )

            time.sleep(2)

        except Exception as e:
            print(f"\n [FORGE] Catastrophic failure: {e}")
            break

    # Cleanup
    print(" [FORGE] Shutting down sandbox...")
    try:
        shutdown_dev_server.invoke({})
    except Exception as e:
        print(f" [Forge] Sandbox shutdown warning: {e}")

    run_engineering_autopsy(task_description, scratchpad, forge_successful)
    print("=" * 60 + "\n")

