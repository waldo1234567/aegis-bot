import os
import shutil
import docker
from docker import errors
from langchain.tools import tool

WORKSPACE_DIR = os.path.abspath(os.path.join(os.getcwd(), "aegis_workspace"))
os.makedirs(WORKSPACE_DIR, exist_ok=True)

try:
    docker_client = docker.from_env()
except errors.DockerException:
    print("[System Error] Docker is not running. Aegis's hands are disabled.")
    docker_client = None

active_container = None
    
def _get_safe_path(filename: str) -> str:
    safe_path = os.path.abspath(os.path.join(WORKSPACE_DIR, filename))
    if not safe_path.startswith(os.path.abspath(WORKSPACE_DIR)):
        raise ValueError("Security Alert: Attempted path traversal.")
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
        filepath = _get_safe_path(filename)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        return f"Successfully wrote {filename} to workspace."
    except Exception as e:
        return f"Failed to write file: {e}"
    
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
    Dependencies installed here will persist until the server is shut down.
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
        output_str = output.decode('utf-8')
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