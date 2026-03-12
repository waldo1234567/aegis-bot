import os
import sys
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request
import asyncio

# This is a hack to allow the server to import the main app's state.
# In a real deployment, this would be handled by a shared state manager like Redis.
# For now, we assume this server is launched from the main.py context.
# We need to add the project root to the python path.
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.insert(0, project_root)

# Now we can attempt to import the application state
try:
    from main import APP_STATE
    # This is a placeholder for a more robust way to access working memory.
    # The deep_dive module holds the active memory object when running.
    import services.deep_dive as deep_dive_module
except (ImportError, ModuleNotFoundError) as e:
    print(f"[Mind Monitor] CRITICAL: Could not import Aegis state from main.py. Using mock data. Error: {e}")
    # Define a mock state if the import fails, so the server can still run for testing.
    APP_STATE = {
        "is_researching": True,
        "current_vad": {"valence": 0.2, "arousal": 0.8, "dominance": 0.7},
        "obsession_stack": ["self-evolution", "systemic failure"],
    }
    class MockWorkingMemory:
        def render(self):
            return "MOCK DATA: Aegis core state not available. This is a fallback view."
    class MockDeepDiveModule:
        def __init__(self):
            self.working_memory = MockWorkingMemory()
    deep_dive_module = MockDeepDiveModule()


app = FastAPI(title="Aegis Mind Monitor")

# Mount static files
static_path = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=static_path), name="static")

# Mount templates
templates_path = os.path.join(os.path.dirname(__file__), "templates")
templates = Jinja2Templates(directory=templates_path)

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/api/state")
async def get_system_state():
    # Access the working memory if a deep dive is active
    working_memory_content = "(idle)"
    if APP_STATE.get("is_researching") and hasattr(deep_dive_module, 'working_memory') and deep_dive_module.working_memory:
        working_memory_content = deep_dive_module.working_memory.render()

    return {
        "status": "researching" if APP_STATE.get("is_researching") else "idle",
        "valence": APP_STATE.get("current_vad", {}).get("valence", 0.5),
        "arousal": APP_STATE.get("current_vad", {}).get("arousal", 0.5),
        "dominance": APP_STATE.get("current_vad", {}).get("dominance", 0.5),
        "working_memory": working_memory_content,
        "obsession_stack": APP_STATE.get("obsession_stack", []),
    }

# This allows running the server directly for testing purposes
if __name__ == "__main__":
    import uvicorn
    print("[Mind Monitor] Running in standalone test mode.")
    uvicorn.run(app, host="0.0.0.0", port=8000)
