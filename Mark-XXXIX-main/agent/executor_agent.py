import json
import threading
from agent.base_agent import BaseAgent, AgentContext


EXECUTOR_PROMPT = """You are TASK CORE AGENT (A5) — the execution module of MARK XXXIX.

Your job: execute the planned steps using available tools.

Available tools:
- web_search(query) — search the web
- file_controller(action, path, content) — manage files
- browser_control(action, url, query) — control browser
- code_helper(action, description, language) — write/run code
- computer_control(action, keys, text, x, y) — system control
- open_app(app_name) — open applications
- screen_process(text, angle) — analyze screen
- weather_report(city) — get weather
- flight_finder(origin, destination, date) — find flights

Return valid JSON:
{
  "executed_steps": ["result 1", "result 2"],
  "success": true,
  "output": "concise result summary"
}"""  # noqa: E501


def _call_tool(tool: str, params: dict) -> str:
    """Execute a tool call - mirrors the pattern from executor.py"""
    try:
        if tool == "web_search":
            from actions.web_search import web_search
            return web_search(parameters=params, player=None) or "Done."
        elif tool == "file_controller":
            from actions.file_controller import file_controller
            return file_controller(parameters=params, player=None) or "Done."
        elif tool == "browser_control":
            from actions.browser_control import browser_control
            return browser_control(parameters=params, player=None) or "Done."
        elif tool == "code_helper":
            from actions.code_helper import code_helper
            return code_helper(parameters=params, player=None, speak=None) or "Done."
        elif tool == "computer_control":
            from actions.computer_control import computer_control
            return computer_control(parameters=params, player=None) or "Done."
        elif tool == "open_app":
            from actions.open_app import open_app
            return open_app(parameters=params, player=None) or "Done."
        elif tool == "screen_process":
            from actions.screen_processor import screen_process
            screen_process(parameters=params, player=None)
            return "Screen captured and analyzed."
        elif tool == "weather_report":
            from actions.weather_report import weather_action
            return weather_action(parameters=params, player=None) or "Done."
        elif tool == "flight_finder":
            from actions.flight_finder import flight_finder
            return flight_finder(parameters=params, player=None, speak=None) or "Done."
        elif tool == "computer_settings":
            from actions.computer_settings import computer_settings
            return computer_settings(parameters=params, player=None) or "Done."
        elif tool == "desktop_control":
            from actions.desktop import desktop_control
            return desktop_control(parameters=params, player=None) or "Done."
        elif tool == "reminder":
            from actions.reminder import reminder
            return reminder(parameters=params, player=None) or "Done."
        elif tool == "send_message":
            from actions.send_message import send_message
            return send_message(parameters=params, player=None) or "Done."
        elif tool == "youtube_video":
            from actions.youtube_video import youtube_video
            return youtube_video(parameters=params, player=None) or "Done."
        elif tool == "game_updater":
            from actions.game_updater import game_updater
            return game_updater(parameters=params, player=None, speak=None) or "Done."
        else:
            return f"[Unknown tool: {tool}]"
    except Exception as e:
        return f"[Tool error: {e}]"


class ExecutorAgent(BaseAgent):
    def __init__(self):
        super().__init__("TaskCore", "Executor", EXECUTOR_PROMPT)

    def run(self, context: AgentContext, speak=None) -> AgentContext:
        context.status[self.name] = "running"
        steps = context.plan if isinstance(context.plan, list) else []
        results = []

        for step in steps:
            if not isinstance(step, dict):
                continue
            tool = step.get("tool", "")
            params = step.get("parameters", {})
            desc = step.get("description", "")

            if not tool:
                results.append(f"[No tool specified for: {desc}]")
                continue

            result = _call_tool(tool, params)
            results.append(f"[{tool}] {desc[:60]}: {result[:100]}")

        context.execution_results = results
        context.status[self.name] = "completed"
        return context
