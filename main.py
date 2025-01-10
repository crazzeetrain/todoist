import os
import requests
from fastapi import FastAPI, Request, Query
from fastapi.responses import RedirectResponse, JSONResponse
from dotenv import load_dotenv

load_dotenv()

# -------------------------------------------------------------------
#  REPLACE these if you'd like to store your secrets in environment 
#  variables during deployment. Otherwise, we'll override them in 
#  the hosting platform's Settings. 
# -------------------------------------------------------------------
TODOIST_CLIENT_ID = os.getenv("TODOIST_CLIENT_ID", "REPLACE_TODOIST_CLIENT_ID")
TODOIST_CLIENT_SECRET = os.getenv("TODOIST_CLIENT_SECRET", "REPLACE_TODOIST_CLIENT_SECRET")

# We’re using an in-memory dict (for the single "demo_user") to store tokens.
# This resets if you redeploy your server.
USER_TOKENS = {}

app = FastAPI(
    title="My Todoist GPT Plugin",
    description="A plugin that connects ChatGPT to Todoist",
    version="0.1.0"
)

# -------------------------------------------------------------------
# 1) A simple test endpoint
# -------------------------------------------------------------------
@app.get("/hello")
def say_hello():
    return {"message": "Hello from the GPT Todoist plugin! This is working."}

# -------------------------------------------------------------------
# 2) OAuth Step: Start authorization
# -------------------------------------------------------------------
@app.get("/oauth/authorize")
def oauth_authorize(user_id: str = "demo_user"):
    """
    1. ChatGPT or user calls this endpoint to begin OAuth with Todoist.
    2. We redirect to Todoist for the user to grant permissions.
    """
    # We request scopes for read/write, data deletion, and project deletion
    scopes = "data:read_write,data:delete,project:delete"
    state = user_id  # this can be anything unique

    authorize_url = (
        "https://todoist.com/oauth/authorize"
        f"?client_id={TODOIST_CLIENT_ID}"
        f"&scope={scopes}"
        f"&state={state}"
    )
    return RedirectResponse(authorize_url)

# -------------------------------------------------------------------
# 3) OAuth Step: Callback
# -------------------------------------------------------------------
@app.get("/oauth/callback")
def oauth_callback(code: str, state: str):
    """
    After user grants permission in Todoist, we get redirected here with a "code".
    We'll exchange it for an access token.
    """
    token_url = "https://todoist.com/oauth/access_token"
    payload = {
        "client_id": TODOIST_CLIENT_ID,
        "client_secret": TODOIST_CLIENT_SECRET,
        "code": code
    }
    resp = requests.post(token_url, data=payload)
    if resp.status_code == 200:
        data = resp.json()
        access_token = data["access_token"]
        # store the token in memory
        USER_TOKENS[state] = access_token
        return JSONResponse({"message": "OAuth success!", "access_token": access_token})
    else:
        return JSONResponse(
            {"error": "Failed to exchange token", "details": resp.text},
            status_code=400
        )

# -------------------------------------------------------------------
# 4) Utility: Get user token from memory
# -------------------------------------------------------------------
def get_token(user_id: str = "demo_user"):
    token = USER_TOKENS.get(user_id)
    if not token:
        # user not authorized
        raise ValueError("No token found for user. Complete OAuth first.")
    return token

# -------------------------------------------------------------------
# 5) Endpoint: Create a Todoist task
# -------------------------------------------------------------------
@app.post("/create_task")
async def create_task(request: Request):
    """
    ChatGPT calls this to create a new task in Todoist.
    Expects JSON with keys:
      user_id, content, project_id, section_id, due_string, labels, priority
    """
    data = await request.json()
    user_id = data.get("user_id", "demo_user")
    content = data.get("content", "Untitled Task")
    project_id = data.get("project_id")
    section_id = data.get("section_id")
    due_string = data.get("due_string")  # e.g. "Tomorrow at 14:00"
    labels = data.get("labels", [])      # e.g. ["@phone", "@computer"]
    priority = data.get("priority")      # e.g. 1..4 (4 is highest priority in the API)

    try:
        token = get_token(user_id)
    except ValueError:
        return JSONResponse({"error": "User not authorized. Please authorize first."}, status_code=401)

    url = "https://api.todoist.com/rest/v2/tasks"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    payload = {"content": content}
    if project_id:
        payload["project_id"] = project_id
    if section_id:
        payload["section_id"] = section_id
    if due_string:
        payload["due_string"] = due_string
    if labels:
        payload["labels"] = labels
    if priority:
        payload["priority"] = priority

    resp = requests.post(url, headers=headers, json=payload)
    if resp.status_code in [200, 201]:
        return {"message": "Task created.", "task": resp.json()}
    else:
        return JSONResponse(
            {"error": "Failed to create task", "details": resp.text},
            status_code=400
        )

# -------------------------------------------------------------------
# 6) Endpoint: Get Projects (lists all projects, includes ID)
# -------------------------------------------------------------------
@app.get("/get_projects")
def get_projects(user_id: str = "demo_user"):
    """
    ChatGPT calls this to list all projects, so user can find IDs
    to create tasks, or do other actions.
    """
    try:
        token = get_token(user_id)
    except ValueError:
        return JSONResponse({"error": "User not authorized. Please authorize first."}, status_code=401)

    url = "https://api.todoist.com/rest/v2/projects"
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(url, headers=headers)
    if resp.status_code == 200:
        return {"projects": resp.json()}
    else:
        return JSONResponse(
            {"error": "Failed to get projects", "details": resp.text},
            status_code=400
        )

# -------------------------------------------------------------------
# 7) Endpoint: Delete a Project
# -------------------------------------------------------------------
@app.delete("/delete_project")
async def delete_project(request: Request):
    """
    Expects JSON: { "user_id": "demo_user", "project_id": 123456 }
    """
    data = await request.json()
    user_id = data.get("user_id", "demo_user")
    project_id = data.get("project_id")

    try:
        token = get_token(user_id)
    except ValueError:
        return JSONResponse({"error": "User not authorized. Please authorize first."}, status_code=401)

    url = f"https://api.todoist.com/rest/v2/projects/{project_id}"
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.delete(url, headers=headers)
    if resp.status_code in [200, 204]:
        return {"message": f"Project {project_id} deleted."}
    else:
        return JSONResponse(
            {"error": "Failed to delete project", "details": resp.text},
            status_code=400
        )

# -------------------------------------------------------------------
# 8) Endpoint: Delete a Task
# -------------------------------------------------------------------
@app.delete("/delete_task")
async def delete_task(request: Request):
    """
    Expects JSON: { "user_id": "demo_user", "task_id": 123456 }
    """
    data = await request.json()
    user_id = data.get("user_id", "demo_user")
    task_id = data.get("task_id")

    try:
        token = get_token(user_id)
    except ValueError:
        return JSONResponse({"error": "User not authorized. Please authorize first."}, status_code=401)

    url = f"https://api.todoist.com/rest/v2/tasks/{task_id}"
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.delete(url, headers=headers)
    if resp.status_code in [200, 204]:
        return {"message": f"Task {task_id} deleted."}
    else:
        return JSONResponse(
            {"error": "Failed to delete task", "details": resp.text},
            status_code=400
        )

# -------------------------------------------------------------------
# 9) Endpoint: List Tasks from a Project
# -------------------------------------------------------------------
@app.get("/get_tasks")
def get_tasks(
    user_id: str = Query("demo_user"),
    project_id: int = Query(None)
):
    """
    If project_id is provided, returns tasks for that project.
    If not provided, returns all tasks.
    """
    try:
        token = get_token(user_id)
    except ValueError:
        return JSONResponse({"error": "User not authorized. Please authorize first."}, status_code=401)

    url = "https://api.todoist.com/rest/v2/tasks"
    headers = {"Authorization": f"Bearer {token}"}

    params = {}
    if project_id:
        params["project_id"] = project_id

    resp = requests.get(url, headers=headers, params=params)
    if resp.status_code == 200:
        return {"tasks": resp.json()}
    else:
        return JSONResponse(
            {"error": "Failed to get tasks", "details": resp.text},
            status_code=400
        )
