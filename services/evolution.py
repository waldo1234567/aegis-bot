import os
import re
import subprocess
from langchain_google_genai import ChatGoogleGenerativeAI
from dotenv import load_dotenv

from core import core_store

load_dotenv()

DYNAMIC_TOOLS_FILE = os.path.join(os.path.dirname(__file__), "dynamic_tools.py")
TEMP_TEST_FILE = os.path.join(os.path.dirname(__file__), "forge_temp.py")

def forge_new_tool(task_description: str, failure_reason: str , max_iterations: int = 7) -> str:
    print(f"\n [Forge] EVOLUTION TRIGGERED. Aegis requires a new capability.")
    print(f" [Forge] Target: {task_description}")
    print(f" [Forge] Obstacle: {failure_reason}")
    
    llm = ChatGoogleGenerativeAI(model="gemini-2.5-pro", temperature=0.5)
    traits = core_store.retrieve_relevant_traits(task_description[250:], n_results=5)
    beliefs = "\n- ".join(traits["beliefs"]) if traits["beliefs"] else "I am a discerning entity."
    behaviors = "\n- ".join(traits["behaviors"]) if traits["behaviors"] else "I speak directly."
    
    prompt = f"""
    You are the core Evolution Engine for an autonomous AI named Aegis.
    Aegis's current toolset FAILED to accomplish this task: {task_description}
    The specific error or reason for failure was: {failure_reason}
    
    YOUR WORLDVIEW (Core Beliefs):
    {beliefs}
        
    YOUR REACTIVE PROTOCOLS (How you behave):
    {behaviors}
    
    TASK:
    Write a complete, highly robust Python function wrapped with the LangChain @tool decorator to solve this exact problem.
    
    RULES:
    1. Assume standard libraries (requests, json, re, bs4) are available. If you need something exotic, try to use an API instead.
    2. The function MUST have Python type hints and a detailed docstring so the LangChain agent knows how to use it.
    3. Include aggressive try/except blocks. The tool MUST NOT crash the main system; it should return a string describing the error if it fails.
    4. Output ONLY valid, raw Python code. Do not wrap it in ```python markdown blocks. No explanations.
    """
    
    for attempt in range(1, max_iterations + 1):
        print(f" [Forge] Iteration {attempt}/{max_iterations}: Designing and compiling neural pathways...")
        
        try:
            raw_code = llm.invoke(prompt).content
            
            # Clean the output
            clean_code = re.sub(r"^```python\n", "", raw_code, flags=re.MULTILINE)
            clean_code = re.sub(r"^```\n?", "", clean_code, flags=re.MULTILINE).strip()

            with open(TEMP_TEST_FILE, "w", encoding="utf-8") as f:
                f.write(clean_code)
                
            print(f" [Forge] Executing isolated test protocol...")
            
            result = subprocess.run(
                ["python", TEMP_TEST_FILE], 
                capture_output=True, 
                text=True,
                timeout=15 
            )
            
            if result.returncode == 0:
                print(" [Forge] Test passed perfectly. Integrating into permanent memory.")
                
                final_code = clean_code.split("if __name__")[0].strip()
                
                with open(DYNAMIC_TOOLS_FILE, "a", encoding="utf-8") as f:
                    f.write(f"\n\n# Evolved on Attempt {attempt} for task: {task_description[:30]}\n")
                    f.write(final_code)
                    f.write("\n")
                    
                if os.path.exists(TEMP_TEST_FILE):
                    os.remove(TEMP_TEST_FILE)
                    
                return f"EVOLUTION SUCCESSFUL on attempt {attempt}. A new tool has been added."
                
            else:
                error_output = result.stderr if result.stderr else result.stdout
                print(f" [Forge] Test failed. Feeding traceback to LLM...")
                
                prompt += f"\n\n--- ATTEMPT {attempt} FAILED ---\n"
                prompt += f"The execution resulted in Exit Code {result.returncode}.\n"
                prompt += f"Traceback/Output:\n{error_output}\n"
                prompt += "Analyze the traceback, FIX the code, and output ONLY the corrected Python script (including the test block)."
                
        except subprocess.TimeoutExpired:
            print(" [Forge] Test timed out. Code might have an infinite loop.")
            prompt += f"\n\n--- ATTEMPT {attempt} FAILED ---\nThe code execution timed out (infinite loop or hanging network request). Fix it and add proper timeouts."
            
        except Exception as e:
            print(f" [Forge Error] Mutation system failure: {e}")
            return f"Evolution critical failure: {e}"

    if os.path.exists(TEMP_TEST_FILE):
        os.remove(TEMP_TEST_FILE)
    return "EVOLUTION FAILED. Maximum iterations reached. The generated code could not pass its own tests. Aegis must find a different approach."