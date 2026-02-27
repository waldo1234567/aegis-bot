import json
import os
import logging
from typing import Any, Dict
from filelock import FileLock, Timeout

# Configure a basic logger for this module.
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] [%(levelname)s] [%(name)s] - %(message)s')
log = logging.getLogger(__name__)

# Define a stable path for the state file, located one level above the workspace.
# This prevents it from being accidentally wiped and is independent of CWD.
_current_dir = os.path.dirname(os.path.abspath(__file__))
STATE_FILE_PATH = os.path.join(_current_dir, "aegis_state.json")
LOCK_FILE_PATH = f"{STATE_FILE_PATH}.lock"

def save_state(data: Dict[str, Any]):
    """Serializes the core Aegis state to a JSON file with concurrency control."""
    lock = FileLock(LOCK_FILE_PATH, timeout=5)
    try:
        with lock:
            with open(STATE_FILE_PATH, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
    except Timeout:
        log.error("Could not acquire lock to save state. Another process may be holding it.")
    except (TypeError, OSError) as e:
        log.error(f"Failed to save state to {STATE_FILE_PATH}: {e}", exc_info=True)

def load_state() -> Dict[str, Any]:
    """Loads the core Aegis state from the JSON file with concurrency control."""
    if not os.path.exists(STATE_FILE_PATH):
        return {}

    lock = FileLock(LOCK_FILE_PATH, timeout=5)
    try:
        with lock:
            with open(STATE_FILE_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Timeout:
        log.error("Could not acquire lock to load state. Another process may be holding it.")
        return {}
    except (json.JSONDecodeError, FileNotFoundError) as e:
        log.warning(f"Could not load or parse state file {STATE_FILE_PATH}: {e}")
        return {}
    except OSError as e:
        log.error(f"File system error loading state from {STATE_FILE_PATH}: {e}", exc_info=True)
        return {}
