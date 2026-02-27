import sys
import os
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# Add the parent directory to the Python path to allow importing 'aegis_state'
# This makes the server runnable from within the 'mind_monitor' directory.
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

try:
    from aegis_state import load_state
except ImportError:
    print("CRITICAL: Could not import 'aegis_state'. Ensure it is in the parent directory.")
    # Define a dummy function to allow the server to start for debugging.
    def load_state():
        return {"error": "Failed to load aegis_state module."}

app = FastAPI(title="Aegis Mind Monitor")

# Mount the 'static' directory to serve index.html, css, and js
static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/api/state")
async def get_aegis_state():
    """Endpoint to fetch the latest state of Aegis from the shared JSON file."""
    try:
        state = load_state()
        if not state:
            # Return a 204 No Content if the state file is empty or doesn't exist yet
            return {}
        return state
    except Exception as e:
        # This provides a more informative error to the frontend if something goes wrong.
        raise HTTPException(status_code=500, detail=f"Error reading state file: {e}")

@app.get("/")
async def read_root():
    """Serve the main dashboard HTML file."""
    return FileResponse(os.path.join(static_dir, 'index.html'))

# To run this server:
# uvicorn mind_monitor.server:app --reload
