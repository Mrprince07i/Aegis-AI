import json
from agent.base_agent import BaseAgent, AgentContext


VALIDATOR_PROMPT = """You are GOAL AGENT (A6) — the validation and output module of MARK XXXIX.

Your job: review what was accomplished and produce a final summary.

Return valid JSON:
{
  "success": true,
  "summary": "one-sentence summary of what was accomplished",
  "details": ["detail 1", "detail 2"],
  "suggestions": ["follow-up suggestion 1"],
  "confidence": 0.95
}"""  # noqa: E501


class ValidatorAgent(BaseAgent):
    def __init__(self):
        super().__init__("Goal", "Validator", VALIDATOR_PROMPT)

    def run(self, context: AgentContext, speak=None) -> AgentContext:
        context.status[self.name] = "running"
        execution = "\n".join(context.execution_results[-5:]) if context.execution_results else "No steps executed"
        research = context.research[-1] if context.research else ""
        memory = context.memory[-1] if context.memory else ""

        prompt = f"""Goal: {context.goal}
Research findings: {research[:300]}
Memory context: {memory[:300]}
Execution results: {execution[:500]}

Evaluate and summarize what was accomplished."""

        result = self._ask_llm(prompt)
        try:
            data = self._extract_json(result)
            context.final_output = data.get("summary", str(data))
        except Exception:
            context.final_output = result

        context.status[self.name] = "completed"
        return context
