import json
import os

# This path assumes the dumper is called from the root of the project,
# and the state file should be accessible to other processes.
WORKSPACE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'aegis_workspace'))
STATE_FILE_PATH = os.path.join(WORKSPACE_DIR, 'aegis_state.json')

def dump_state(app_state: dict):
    """Serializes the application's core state to a JSON file."""
    try:
        # Ensure the workspace directory exists
        os.makedirs(WORKSPACE_DIR, exist_ok=True)

        # Extract relevant data for the monitor
        monitor_state = {
            "valence": app_state.get("current_vad", {}).get("valence", 0.5),
            "arousal": app_state.get("current_vad", {}).get("arousal", 0.5),
            "dominance": app_state.get("current_vad", {}).get("dominance", 0.5),
            "is_researching": app_state.get("is_researching", False),
            "current_topic": app_state.get("obsession_stack", ["None"])[-1] if app_state.get("obsession_stack") else "Idle",
        }

        with open(STATE_FILE_PATH, 'w') as f:
            json.dump(monitor_state, f, indent=2)

    except Exception as e:
        # This function should not crash the main application
        print(f"[State Dumper Error] Failed to write state to {STATE_FILE_PATH}: {e}")
