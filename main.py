"""
Task Board — Kanban project management for Imperal Cloud.

Features:
- Kanban columns: To Do, In Progress, Done
- Projects with color coding
- Priorities: high, medium, low
- Due dates
- AI: auto-suggest tasks, summarize progress
- IPC: other extensions can create/update tasks
"""
from __future__ import annotations
import time
from pydantic import BaseModel, Field
from imperal_sdk import Extension, ChatExtension, ActionResult
from imperal_sdk.ui import (
    Page, Section, Stack, Grid, Tabs,
    Header, Text, Stat, Stats, Badge, Divider, Icon,
    Card, Button, Image,
    Form, Input, TextArea, Select,
    List, ListItem, Empty, Alert,
    Progress, KeyValue, Html,
    Call, Open,
)

ext = Extension("taskboard", version="1.0.0", config_defaults={
    "projects": ["General", "Work", "Personal"],
    "columns": ["To Do", "In Progress", "Review", "Done"],
})

chat = ChatExtension(
    ext,
    tool_name="tasks",
    description="Manage tasks and projects. Create, update, move, complete tasks. "
                "Organize by project, set priorities, track progress.",
    system_prompt="You are a task management assistant. Help users organize their work. "
                  "Be concise. When creating tasks, ask for title and project at minimum.",
    max_rounds=10,
)


# ======================================================================
# Chat Functions
# ======================================================================

class CreateTaskParams(BaseModel):
    title: str = Field(description="Task title")
    project: str = Field(default="General", description="Project name")
    priority: str = Field(default="medium", description="Priority: high, medium, low")
    column: str = Field(default="To Do", description="Column: To Do, In Progress, Review, Done")
    description: str = Field(default="", description="Task description")
    due_date: str = Field(default="", description="Due date (YYYY-MM-DD)")

@chat.function("create_task", description="Create a new task", action_type="write", event="task.created")
async def create_task(ctx, params: CreateTaskParams) -> ActionResult:
    """Create a new task on the board."""
    task = {
        "title": params.title,
        "project": params.project,
        "priority": params.priority,
        "column": params.column,
        "description": params.description,
        "due_date": params.due_date,
        "created_at": time.time(),
        "completed_at": None,
    }
    doc = await ctx.store.create("tasks", task)
    return ActionResult.success(
        data={"task": task, "id": doc},
        summary=f"Created: {params.title} [{params.project}] ({params.priority})",
        refresh_panels=["board", "sidebar"],
    )


class UpdateTaskParams(BaseModel):
    task_id: str = Field(description="Task ID")
    column: str = Field(default="", description="Move to column")
    priority: str = Field(default="", description="New priority")
    title: str = Field(default="", description="New title")

@chat.function("update_task", description="Update or move a task", action_type="write", event="task.updated")
async def update_task(ctx, params: UpdateTaskParams) -> ActionResult:
    """Update a task — move between columns, change priority, rename."""
    task = await ctx.store.get("tasks", params.task_id)
    if not task:
        return ActionResult.error("Task not found")

    if params.column:
        task["column"] = params.column
        if params.column == "Done":
            task["completed_at"] = time.time()
    if params.priority:
        task["priority"] = params.priority
    if params.title:
        task["title"] = params.title

    await ctx.store.update("tasks", params.task_id, task)
    return ActionResult.success(
        data=task,
        summary=f"Updated: {task['title']}",
        refresh_panels=["board"],
    )


class CompleteTaskParams(BaseModel):
    task_id: str = Field(description="Task ID to complete")

@chat.function("complete_task", description="Mark task as done", action_type="write", event="task.completed")
async def complete_task(ctx, params: CompleteTaskParams) -> ActionResult:
    """Move task to Done column."""
    task = await ctx.store.get("tasks", params.task_id)
    if not task:
        return ActionResult.error("Task not found")
    task["column"] = "Done"
    task["completed_at"] = time.time()
    await ctx.store.update("tasks", params.task_id, task)
    return ActionResult.success(data=task, summary=f"Completed: {task['title']}", refresh_panels=["board", "sidebar"])


class DeleteTaskParams(BaseModel):
    task_id: str = Field(description="Task ID to delete")

@chat.function("delete_task", description="Delete a task", action_type="write")
async def delete_task(ctx, params: DeleteTaskParams) -> ActionResult:
    """Delete a task permanently."""
    await ctx.store.delete("tasks", params.task_id)
    return ActionResult.success(summary="Task deleted", refresh_panels=["board", "sidebar"])


class ListTasksParams(BaseModel):
    project: str = Field(default="", description="Filter by project")
    column: str = Field(default="", description="Filter by column")

@chat.function("list_tasks", description="List all tasks", action_type="read")
async def list_tasks(ctx, params: ListTasksParams) -> ActionResult:
    """List tasks with optional filters."""
    tasks = await ctx.store.query("tasks", {})
    if not isinstance(tasks, list):
        tasks = []
    if params.project:
        tasks = [t for t in tasks if t.get("project") == params.project]
    if params.column:
        tasks = [t for t in tasks if t.get("column") == params.column]
    return ActionResult.success(
        data={"tasks": tasks, "count": len(tasks)},
        summary=f"{len(tasks)} tasks found",
    )


class SuggestTasksParams(BaseModel):
    context: str = Field(default="", description="What are you working on?")

@chat.function("suggest_tasks", description="AI suggests tasks based on context", action_type="read")
async def suggest_tasks(ctx, params: SuggestTasksParams) -> ActionResult:
    """AI suggests tasks you should create."""
    tasks = await ctx.store.query("tasks", {})
    existing = [t.get("title", "") for t in tasks] if isinstance(tasks, list) else []

    result = await ctx.ai.complete(
        f"Based on context: '{params.context}'\nExisting tasks: {existing[:10]}\n\n"
        "Suggest 5 new tasks. Return as JSON array: [{\"title\": \"...\", \"priority\": \"high/medium/low\", \"project\": \"...\"}]",
        system="You are a productivity expert. Suggest actionable, specific tasks.",
    )
    return ActionResult.success(data={"suggestions": result.text}, summary="5 tasks suggested")


# ======================================================================
# IPC — other extensions can create tasks
# ======================================================================

@ext.expose("create_task")
async def ipc_create_task(ctx, title: str = "", project: str = "General",
                          priority: str = "medium") -> ActionResult:
    """IPC: Create a task from another extension."""
    params = CreateTaskParams(title=title, project=project, priority=priority)
    return await create_task(ctx, params)

@ext.expose("list_tasks")
async def ipc_list_tasks(ctx, project: str = "", column: str = "") -> ActionResult:
    """IPC: List tasks."""
    params = ListTasksParams(project=project, column=column)
    return await list_tasks(ctx, params)


# ======================================================================
# DUI Panels
# ======================================================================

PRIORITY_COLORS = {"high": "red", "medium": "yellow", "low": "green"}
PROJECT_COLORS = {"General": "blue", "Work": "purple", "Personal": "green"}


@ext.panel("board", slot="main", title="Task Board", icon="kanban-square")
async def board_panel(ctx):
    """Main board — Kanban columns."""
    all_tasks = await ctx.store.query("tasks", {})
    tasks = all_tasks if isinstance(all_tasks, list) else []
    columns = ctx.config.get("columns", ["To Do", "In Progress", "Review", "Done"])

    # Build Kanban tabs — one tab per column
    tabs = []
    for col in columns:
        col_tasks = [t for t in tasks if t.get("column") == col]
        col_tasks.sort(key=lambda t: {"high": 0, "medium": 1, "low": 2}.get(t.get("priority", "medium"), 1))

        if not col_tasks:
            content = Empty(message=f"No tasks in {col}", icon="inbox")
        else:
            items = []
            for t in col_tasks:
                p = t.get("priority", "medium")
                proj = t.get("project", "General")
                items.append(ListItem(
                    id=str(t.get("_id", t.get("created_at", ""))),
                    title=t.get("title", "Untitled"),
                    subtitle=t.get("description", "")[:60] if t.get("description") else "",
                    icon="circle-dot" if col != "Done" else "check-circle",
                    badge=Badge(label=proj, color=PROJECT_COLORS.get(proj, "gray")),
                    meta=p,
                    actions=[
                        {"label": "Complete", "on_click": Call(function="complete_task", task_id=str(t.get("_id", "")))},
                        {"label": "Delete", "on_click": Call(function="delete_task", task_id=str(t.get("_id", "")))},
                    ] if col != "Done" else [
                        {"label": "Delete", "on_click": Call(function="delete_task", task_id=str(t.get("_id", "")))},
                    ],
                ))
            content = List(items=items)

        count = len(col_tasks)
        tabs.append({
            "id": col.lower().replace(" ", "-"),
            "label": f"{col} ({count})",
            "content": content,
        })

    return Page(
        title="Task Board",
        subtitle=f"{len(tasks)} tasks across {len(columns)} columns",
        children=[
            # Quick add
            Form(
                action="create_task",
                submit_label="Add Task",
                children=[
                    Stack(direction="h", children=[
                        Input(placeholder="New task...", param_name="title"),
                        Select(
                            options=[{"value": p, "label": p} for p in ctx.config.get("projects", ["General"])],
                            value="General",
                            param_name="project",
                        ),
                        Select(
                            options=[
                                {"value": "high", "label": "High"},
                                {"value": "medium", "label": "Medium"},
                                {"value": "low", "label": "Low"},
                            ],
                            value="medium",
                            param_name="priority",
                        ),
                    ]),
                ],
            ),
            Divider(),
            Tabs(tabs=tabs),
        ],
    )


@ext.panel("sidebar", slot="left", title="Task Board", icon="kanban-square")
async def sidebar_panel(ctx):
    """Left sidebar — stats + projects + quick actions."""
    all_tasks = await ctx.store.query("tasks", {})
    tasks = all_tasks if isinstance(all_tasks, list) else []

    todo = len([t for t in tasks if t.get("column") == "To Do"])
    progress = len([t for t in tasks if t.get("column") == "In Progress"])
    review = len([t for t in tasks if t.get("column") == "Review"])
    done = len([t for t in tasks if t.get("column") == "Done"])
    high = len([t for t in tasks if t.get("priority") == "high" and t.get("column") != "Done"])

    projects = ctx.config.get("projects", ["General"])

    return Page(
        title="Task Board",
        children=[
            Button(
                label="New Task",
                variant="primary",
                icon="plus",
                full_width=True,
                on_click=Call(function="create_task", title="New task", project="General"),
            ),
            Divider(),
            Stats(children=[
                Stat(label="To Do", value=str(todo), icon="circle", color="blue"),
                Stat(label="In Progress", value=str(progress), icon="loader", color="yellow"),
                Stat(label="Done", value=str(done), icon="check-circle", color="green"),
            ]),
            Divider(),
            *(
                [Alert(message=f"{high} high priority tasks!", title="Attention", type="warning"), Divider()]
                if high > 0 else []
            ),
            Section(
                title="Projects",
                collapsible=True,
                children=[
                    List(items=[
                        ListItem(
                            id=f"proj-{p}",
                            title=p,
                            meta=str(len([t for t in tasks if t.get("project") == p])),
                            badge=Badge(label=str(len([t for t in tasks if t.get("project") == p and t.get("column") != "Done"])), color=PROJECT_COLORS.get(p, "gray")),
                            on_click=Call(function="list_tasks", project=p),
                        )
                        for p in projects
                    ]),
                ],
            ),
            Divider(),
            Section(
                title="Quick Actions",
                collapsible=True,
                children=[
                    List(items=[
                        ListItem(id="suggest", title="AI Suggest Tasks", icon="sparkles", on_click=Call(function="suggest_tasks", context="my current work")),
                        ListItem(id="review", title="Show In Review", icon="eye", on_click=Call(function="list_tasks", column="Review")),
                        ListItem(id="overdue", title="High Priority", icon="alert-triangle", on_click=Call(function="list_tasks", column="To Do")),
                    ]),
                ],
            ),
        ],
    )


# ======================================================================
# Lifecycle
# ======================================================================

@ext.on_install
async def on_install(ctx):
    return ActionResult.success(summary="Task Board installed! Start adding tasks.")

@ext.health_check
async def health(ctx):
    tasks = await ctx.store.query("tasks", {})
    count = len(tasks) if isinstance(tasks, list) else 0
    return ActionResult.success(data={"status": "healthy", "tasks": count})
