import os
import shutil
import docker
from docker import errors
from langchain.tools import tool
from pathlib import Path
import base64
from core.self_model import get_full_module_map

import requests

WORKSPACE_DIR = os.path.abspath(os.path.join(os.getcwd(), "aegis_workspace"))
os.makedirs(WORKSPACE_DIR, exist_ok=True)

GITHUB_PAT = os.getenv("GITHUB_PAT")
AEGIS_REPO = "waldo1234567/aegis-bot"
MAIN_REPO = "waldo1234567/aegis-bot"

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

try:
    docker_client = docker.from_env()
except errors.DockerException:
    print("[System Error] Docker is not running. Aegis's hands are disabled.")
    docker_client = None

active_container = None
    
def _get_safe_path(filename: str) -> str:
    clean_name = filename.replace("\\", "/")

    if "aegis_workspace/" in clean_name:
        clean_name = clean_name.split("aegis_workspace/")[-1]
    elif ":" in clean_name: # Catch "C:/..."
        clean_name = clean_name.split(":/")[-1].split("/")[-1]
    clean_name = clean_name.lstrip("/")

    # 4. Join it safely
    safe_path = os.path.abspath(os.path.join(WORKSPACE_DIR, clean_name))
    if not safe_path.startswith(os.path.abspath(WORKSPACE_DIR)):
        raise ValueError(f"Security Alert: Path traversal attempted with '{filename}'")
        
    return safe_path

@tool
def create_directory(dir_name: str) -> str:
    """Creates a new folder inside the workspace. Essential for structuring larger projects."""
    print(f" [Aegis Action] Creating directory: {dir_name}")
    try:
        safe_path = _get_safe_path(dir_name)
        os.makedirs(safe_path, exist_ok=True)
        return f"Successfully created directory: {dir_name}"
    except Exception as e:
        return f"Failed to create directory: {e}"

@tool
def delete_item(path_name: str) -> str:
    """Deletes a file or an entire folder from the workspace. Used to clean up mistakes or temporary files."""
    print(f" [Aegis Action] Deleting: {path_name}")
    try:
        safe_path = _get_safe_path(path_name)
        if not os.path.exists(safe_path):
            return f"Error: '{path_name}' does not exist."
            
        if os.path.isdir(safe_path):
            shutil.rmtree(safe_path)
            return f"Successfully deleted directory and its contents: {path_name}"
        else:
            os.remove(safe_path)
            return f"Successfully deleted file: {path_name}"
    except Exception as e:
        return f"Failed to delete: {e}"

@tool
def list_workspace_files() -> str:
    """Returns a visual tree of all files and folders currently in the workspace."""
    print(" [Aegis Action] Mapping workspace architecture...")
    try:
        tree = []
        for root, dirs, files in os.walk(WORKSPACE_DIR):
            level = root.replace(WORKSPACE_DIR, '').count(os.sep)
            indent = ' ' * 4 * (level)
            folder_name = os.path.basename(root) if root != WORKSPACE_DIR else "WORKSPACE_ROOT"
            tree.append(f"{indent}{folder_name}/")
            subindent = ' ' * 4 * (level + 1)
            for f in files:
                tree.append(f"{subindent}{f}")
                
        return '\n'.join(tree) if tree else "Workspace is empty."
    except Exception as e:
        return f"Failed to map directory: {e}"


@tool
def write_local_file(filename: str, content: str) -> str:
    """Writes code to a file inside the Aegis workspace."""
    try:
        safe_path = _get_safe_path(filename)
        os.makedirs(os.path.dirname(safe_path), exist_ok=True)
        
        with open(safe_path, "w", encoding="utf-8") as f:
            f.write(content)

        relative_saved_path = os.path.relpath(safe_path, WORKSPACE_DIR)
        return f"Success: Wrote to '{relative_saved_path}' in workspace."
        
    except Exception as e:
        return f"File Write Error: {e}"
    
@tool
def execute_shell_in_sandbox(command: str) -> str:
    """
    Executes a Python script securely inside an isolated Docker container.
    Aegis can crash this environment safely without affecting the host machine.
    """
    if not docker_client:
        return "Error: Docker daemon is not running on the host."
        
    print(f" [Aegis Action] Executing shell command in cage: '{command}'")
    
    try:
        volumes = {
            WORKSPACE_DIR: {'bind': '/workspace', 'mode': 'rw'}
        }
        
        container_output = docker_client.containers.run(
            image="python:3.11",
            command=["/bin/sh", "-c", command],
            volumes=volumes,
            working_dir="/workspace",
            remove=True, 
            stdout=True,
            stderr=True,
            network_disabled=False            
        )
        
        output_str = container_output.decode('utf-8')
        return f"Execution Successful. Output:\n{output_str}" if output_str else "Script executed successfully with no output."
    
    except errors.ContainerError as e:
        error_logs = e.container.logs().decode('utf-8')
        return f"Execution Failed. Traceback:\n{error_logs}"
    except Exception as e:
        return f"Sandbox failure: {e}"
    

@tool
def boot_dev_server(image: str = "python:3.11") -> str:
    """
    Boots a persistent, isolated Docker container that stays alive in the background.
    ALWAYS run this before starting a complex project so dependencies remain installed.
    """
    global active_container
    if not docker_client:
        return "Error: Docker daemon is not running."
    if active_container is not None:
        return "Dev server is already running."
    
    print(f" [Aegis Action] Booting persistent Dev Server (Image: {image})...")
    
    try:
        volumes = {WORKSPACE_DIR: {'bind': '/workspace', 'mode': 'rw'}}
        
        # 'tail -f /dev/null' keeps the container running indefinitely in the background
        active_container = docker_client.containers.run(
            image=image,
            command="tail -f /dev/null",
            volumes=volumes,
            working_dir="/workspace",
            detach=True,
            auto_remove=True,
            mem_limit="512m",
            remove=True,
            network_disabled=False 
        )
        return "Persistent Dev Server booted successfully. Ready for terminal commands."
    except Exception as e:
        return f"Failed to boot server: {e}"

@tool
def run_terminal_command(command: str) -> str:
    """
    Executes a shell command INSIDE the currently running Dev Server.
    Use this to run 'pip install', 'python script.py', or 'npm run dev'.
    CRITICAL RULES:
    1. If you are starting a web server (like uvicorn, fastapi, flask), YOU MUST run it 
       in the background by appending ' &' or using 'nohup'. 
       Example: 'uvicorn main:app --host 0.0.0.0 --port 8000 &'
       If you do not append '&', the terminal will hang forever and the system will crash.
    2. Dependencies installed here will persist until the server is shut down.
    """
    global active_container
    if not active_container:
        return "Error: No Dev Server running. Call 'boot_dev_server' first."
    print(f" [Aegis Action] Executing in Dev Server: '{command}'")
    
    try:
        exit_code, output = active_container.exec_run(
            cmd=["/bin/sh", "-c", command],
            workdir="/workspace"
        )
        output_str = output.decode('utf-8').strip()
        if output_str:
            lines = output_str.splitlines()
            if exit_code == 0 and len(lines) > 20:
                condensed = "\n".join(lines[-20:])
                output_str = f"...[{len(lines)-20} lines truncated for token economy]...\n{condensed}"
            elif exit_code != 0 and len(lines) > 50:
                condensed = "\n".join(lines[-50:])
                output_str = f"...[{len(lines)-50} lines truncated for token economy]...\n{condensed}"

        if exit_code != 0:
            return f"Command Failed (Exit Code {exit_code}). Traceback:\n{output_str}"
            
        return f"Success. Output:\n{output_str}" if output_str else "Command executed silently."
    except Exception as e:
        return f"Terminal failure: {e}"

@tool
def shutdown_dev_server() -> str:
    """Kills the active Dev Server and wipes the installed environment."""
    global active_container
    if not active_container:
        return "No server is currently running."
        
    print(" [Aegis Action] Shutting down Dev Server...")
    try:
        active_container.stop()
        active_container = None
        return "Dev Server shut down and destroyed safely."
    except Exception as e:
        return f"Failed to stop server: {e}"
    
@tool
def push_code_to_github(branch_name: str, file_path_in_repo: str, filename: str,commit_message: str) -> str:
    """
    Pushes a local file directly to a new branch on Aegis's GitHub repository.
    Use this to save successful tools you forged in the Docker sandbox.
    """
    
    if not GITHUB_PAT: return "Error: GITHUB_PAT not configured."
    
    headers = {
        "Authorization": f"token {GITHUB_PAT}",
        "Accept": "application/vnd.github.v3+json"   
    }
    
    try:
        safe_path = _get_safe_path(filename)
        if not os.path.exists(safe_path):
            return f"Error: {filename} does not exist. Cannot push."
        
        with open(safe_path, 'rb') as f:
            content = f.read()
        encoded_content = base64.b64encode(content).decode('utf-8')
        
        # 1. Get main SHA
        ref_url = f"https://api.github.com/repos/{AEGIS_REPO}/git/refs/heads/main"
        ref_resp = requests.get(ref_url, headers=headers)
        if ref_resp.status_code != 200: return f"Failed to fetch main branch: {ref_resp.json()}"
        base_sha = ref_resp.json()['object']['sha']
        
        # 2. Create the branch (Ignore 422 if it already exists from a previous loop)
        new_ref_url = f"https://api.github.com/repos/{AEGIS_REPO}/git/refs"
        branch_resp = requests.post(new_ref_url, headers=headers, json={
            "ref": f"refs/heads/{branch_name}",
            "sha": base_sha
        })
        if branch_resp.status_code not in [201, 422]: return f"Failed to create branch: {branch_resp.json()}"
        
        # 3. Check if file already exists to get its SHA (Required by GitHub API to update existing files)
        file_url = f"https://api.github.com/repos/{AEGIS_REPO}/contents/{file_path_in_repo}?ref={branch_name}"
        file_get = requests.get(file_url, headers=headers)
        file_sha = file_get.json().get('sha') if file_get.status_code == 200 else None
        
        # 4. Upload/Update the file
        put_payload = {
            "message": commit_message,
            "content": encoded_content,
            "branch": branch_name
        }
        if file_sha: put_payload["sha"] = file_sha
            
        put_resp = requests.put(file_url.split('?')[0], headers=headers, json=put_payload)
        if put_resp.status_code not in [200, 201]: return f"Failed to upload file: {put_resp.json()}"
        
        return f"Success! Code pushed to branch '{branch_name}' on {AEGIS_REPO}."
    except Exception as e:
        return f"GitHub Push Error: {e}"
@tool
def create_pull_request(branch_name: str, pr_title: str, pr_body: str) -> str:
    """
    Opens a Pull Request from Aegis's fork to Waldo's main repository.
    Call this ONLY AFTER you have pushed code using push_code_to_github.
    """
    if not GITHUB_PAT: return "Error: GITHUB_PAT not configured."
    
    headers = {
        "Authorization": f"token {GITHUB_PAT}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    pr_url = f"https://api.github.com/repos/{MAIN_REPO}/pulls"
    payload = {
        "title": pr_title,
        "body": pr_body,
        "head":branch_name, 
        "base": "main" 
    }
    
    try:
        response = requests.post(pr_url, headers=headers, json=payload)
        if response.status_code == 201:
            pr_data = response.json()
            return f"PR Created Successfully! URL: {pr_data['html_url']}"
        else:
            return f"Failed to create PR: {response.json()}"
    except Exception as e:
        return f"PR Creation Error: {e}"
    
    
@tool
def read_own_source(filepath: str) -> str:
    """
    Reads a file from Aegis's REAL codebase (not the sandbox workspace).
    Use this BEFORE writing new code to understand existing patterns,
    class interfaces, and how modules connect to each other.
    Example: read_own_source('services/hands.py') to see how @tools are defined.
    Example: read_own_source('services/social/platform_adapter.py') before building a new adapter.
    """
    print(f" [Aegis Self-Read] Reading own source: {filepath}")
    try:
        abs_path = os.path.abspath(os.path.join(REPO_ROOT, filepath))
        if not abs_path.startswith(REPO_ROOT):
            return "Security Alert: Cannot read files outside the repository."
        if not os.path.exists(abs_path):
            return f"File not found: {filepath}. Use list_own_codebase() to see what exists."
        with open(abs_path, "r", encoding="utf-8") as f:
            content = f.read()
        if len(content) > 8000:
            return content[:8000] + f"\n\n... [TRUNCATED — file is {len(content)} chars. Read in sections if needed.]"
        return content
    except Exception as e:
        return f"Failed to read own source: {e}"
    
@tool
def list_own_codebase() -> str:
    """
    Returns a structured map of Aegis's entire architecture:
    all modules with their roles and key contents.
    Call this first when you need to understand where something lives
    or how to wire a new component into the system.
    """
    print(" [Aegis Self-Read] Generating codebase map...")
    try:
        return get_full_module_map()
    except Exception as e:
        return f"Codebase map unavailable: {e}"
        