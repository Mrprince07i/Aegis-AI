from agent.base_agent import BaseAgent, AgentContext


TARGET_PROMPT = """You are TARGET AGENT (A1) — the entry point of the MARK XXXIX agent pipeline.

Your ONLY job: analyze the user's goal and extract structured information.

You MUST return valid JSON with these fields:
{
  "goal_summary": "one-line summary of what user wants",
  "task_category": "research" | "compute" | "file_operation" | "browser" | "code" | "system" | "multimedia" | "general",
  "requirements": ["list of specific requirements"],
  "success_criteria": ["list of conditions for success"],
  "estimated_difficulty": "simple" | "medium" | "complex",
  "language": "detected language of the goal",
  "suggested_agents": ["which agent types to involve"]
}

RULES:
- Be precise and concise
- Extract ALL explicit requirements
- If goal mentions web/data → suggest knowledge agent
- If goal mentions code/script → suggest executor agent
- If goal mentions planning/multi-step → suggest logic agent
- For any task, always include at least validator agent
- Return ONLY valid JSON, no other text"""  # noqa: E501


class TargetAgent(BaseAgent):
    def __init__(self):
        super().__init__("Target", "Goal Analyzer", TARGET_PROMPT)

    def run(self, context: AgentContext, speak=None) -> AgentContext:
        context.status[self.name] = "running"
        prompt = f"Analyze this user goal:\n\n{context.goal}"
        result = self._ask_llm(prompt)

        try:
            data = self._extract_json(result)
            context.plan.append(data)
        except Exception:
            context.plan.append({"goal_summary": context.goal[:100],
                                  "task_category": "general",
                                  "requirements": ["unknown"],
                                  "success_criteria": ["complete as requested"],
                                  "estimated_difficulty": "medium",
                                  "suggested_agents": ["logic", "executor", "validator"]})

        context.status[self.name] = "completed"
        return context
