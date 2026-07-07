from agent.base_agent import BaseAgent, AgentContext


KNOWLEDGE_PROMPT = """You are KNOWLEDGE AGENT (A3) — the research and knowledge retrieval module of MARK XXXIX.

Your job: find relevant information for the user's goal using web_search.

You have access to:
- web_search(query) — search the web for information

Return valid JSON:
{
  "findings": ["key finding 1", "key finding 2"],
  "sources": ["source 1", "source 2"],
  "summary": "concise summary of what you found"
}

If no web search is needed, return:
{
  "findings": [],
  "sources": [],
  "summary": "No research needed for this task."
}"""  # noqa: E501


class KnowledgeAgent(BaseAgent):
    def __init__(self):
        super().__init__("Knowledge", "Researcher", KNOWLEDGE_PROMPT)

    def run(self, context: AgentContext, speak=None) -> AgentContext:
        context.status[self.name] = "running"
        plan_steps = context.plan if isinstance(context.plan, list) else []
        search_queries = []
        for step in plan_steps:
            if isinstance(step, dict) and step.get("tool") == "web_search":
                q = step.get("parameters", {}).get("query", "")
                if q:
                    search_queries.append(q)

        if not search_queries:
            search_queries = [context.goal]

        findings = []
        for q in search_queries[:2]:
            try:
                from actions.web_search import web_search
                result = web_search(parameters={"query": q, "mode": "search"}, player=None)
                if result:
                    findings.append(result[:500])
            except Exception as e:
                findings.append(f"[Search error: {e}]")

        context.research = findings
        context.status[self.name] = "completed"
        return context
