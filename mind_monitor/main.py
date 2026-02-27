import json
import os
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

app = FastAPI(title="Aegis Mind Monitor")

# The monitor will run from inside the 'mind_monitor' directory,
# so the state file is in the parent directory.
STATE_FILE_PATH = os.path.join(os.path.dirname(__file__), '..', 'aegis_state.json')

# Mount static files (for CSS)
app.mount("/static", StaticFiles(directory="static"), name="static")

# Setup Jinja2 templates
templates = Jinja2Templates(directory="templates")

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    state_data = {
        "valence": 0.5,
        "arousal": 0.5,
        "dominance": 0.5,
        "is_researching": False,
        "current_topic": "Awaiting State Dump...",
        "recent_memories": ["No memories loaded."]
    }
    try:
        if os.path.exists(STATE_FILE_PATH):
            with open(STATE_FILE_PATH, 'r') as f:
                state_data.update(json.load(f))
    except (json.JSONDecodeError, IOError) as e:
        print(f"Error reading state file: {e}")
        state_data["current_topic"] = f"ERROR: Could not read state file. {e}"

    return templates.TemplateResponse("index.html", {"request": request, "state": state_data})
