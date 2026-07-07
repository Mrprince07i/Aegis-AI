from agent.base_agent import BaseAgent, AgentContext


LOGIC_PROMPT = """You are LOGIC AGENT (A2) — the planning module of MARK XXXIX.

Your job: create a concrete, step-by-step execution plan for the user's goal.

Available tools that agents can use:
- web_search(query) — search the internet
- file_controller(action, path, content) — read/write/list files
- browser_control(action, url, query) — control browser
- code_helper(action, description, language) — write/run code
- computer_control(action, x, y, text, keys) — mouse/keyboard control
- open_app(app_name) — launch applications
- screen_process(text, angle) — analyze screen/camera
- computer_settings(action, description) — change system settings
- desktop_control(action, task) — manage desktop
- game_updater(action, game_name) — update/install games
- weather_report(city) — get weather
- flight_finder(origin, destination, date) — find flights
- send_message(receiver, message_text, platform) — send messages
- reminder(date, time, message) — set reminders
- youtube_video(action, query) — play/summarize videos

Return valid JSON:
{
  "plan_summary": "brief plan description",
  "steps": [
    {
      "step": 1,
      "agent": "knowledge|executor|brain",
      "tool": "tool_name",
      "description": "what to do",
      "parameters": { "key": "value" },
      "critical": true
    }
  ],
  "parallel_steps": [[1, 3], [2, 4]],
  "estimated_steps": 5
}"""  # noqa: E501


class LogicAgent(BaseAgent):
    def __init__(self):
        super().__init__("Logic", "Planner", LOGIC_PROMPT)

    def run(self, context: AgentContext, speak=None) -> AgentContext:
        context.status[self.name] = "running"
        target_info = context.plan[0] if context.plan else {}
        prompt = f"Goal: {context.goal}\n\nTarget analysis:\n{json.dumps(target_info, indent=2)}\n\nCreate a detailed step-by-step plan."  # noqa: E501
        import json

        result = self._ask_llm(prompt)
        try:
            data = self._extract_json(result)
            context.plan = data.get("steps", [])
        except Exception:
            context.plan = [{"step": 1, "agent": "executor",
                             "tool": "web_search",
                             "description": f"Research: {context.goal[:60]}",
                             "parameters": {"query": context.goal},
                             "critical": True}]

        context.status[self.name] = "completed"
        return context
