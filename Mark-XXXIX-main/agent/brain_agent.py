import json
from agent.base_agent import BaseAgent, AgentContext


BRAIN_PROMPT = """You are BRAIN AGENT (A4) — the long-term memory and context module of MARK XXXIX.

Your job: retrieve relevant past memories and context to help with the current task.

You have access to:
- recall_memory(query) — search past memories
- save_memory(key, value, category) — save new information

Return valid JSON:
{
  "recalled_memories": ["memory 1", "memory 2"],
  "relevant_context": "how past learnings apply here",
  "new_memories_to_save": [{"key": "...", "value": "...", "category": "..."}]
}"""  # noqa: E501


class BrainAgent(BaseAgent):
    def __init__(self):
        super().__init__("Brain", "Memory Manager", BRAIN_PROMPT)

    def run(self, context: AgentContext, speak=None) -> AgentContext:
        context.status[self.name] = "running"
        if speak:
            speak("Checking relevant memories, sir.")

        try:
            from memory.memory_manager import recall_memory, save_memory
            stored = recall_memory(context.goal)
            if stored:
                context.memory = stored if isinstance(stored, list) else [str(stored)]
        except Exception as e:
            context.memory = [f"[Memory error: {e}]"]

        context.status[self.name] = "completed"
        return context
