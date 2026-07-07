import json
import threading
import time
from typing import Callable
from agent.base_agent import BaseAgent, AgentContext
from agent.target_agent import TargetAgent
from agent.logic_agent import LogicAgent
from agent.knowledge_agent import KnowledgeAgent
from agent.brain_agent import BrainAgent
from agent.executor_agent import ExecutorAgent
from agent.validator_agent import ValidatorAgent


class AgentManager:
    """Orchestrates the 6-agent pipeline for complex tasks."""

    def __init__(self):
        self.agents: dict[str, BaseAgent] = {
            "target": TargetAgent(),
            "logic": LogicAgent(),
            "knowledge": KnowledgeAgent(),
            "brain": BrainAgent(),
            "executor": ExecutorAgent(),
            "validator": ValidatorAgent(),
        }
        self._pipeline_status: dict[str, str] = {}
        self._current_context: AgentContext | None = None

    def get_pipeline_status(self) -> dict[str, str]:
        """Return current status of all agents for UI display."""
        if self._current_context:
            return dict(self._current_context.status)
        return {}

    def run_pipeline(self, goal: str, speak: Callable | None = None,
                     progress_cb: Callable | None = None) -> str:
        """Run the full agent pipeline for a given goal."""
        context = AgentContext(goal=goal)
        self._current_context = context

        # Phase 1: Analysis (A1 + A2)
        if speak:
            speak("Starting multi-agent analysis, sir.")

        context = self.agents["target"].run(context, speak)
        if progress_cb:
            progress_cb("target", "completed")

        context = self.agents["logic"].run(context, speak)
        if progress_cb:
            progress_cb("logic", "completed")

        # Phase 2: Research & Memory (A3 + A4) - parallel
        if speak:
            speak("Gathering intelligence and context.")

        t1 = threading.Thread(target=lambda: self._run_agent_safe("knowledge", context, speak, progress_cb))
        t2 = threading.Thread(target=lambda: self._run_agent_safe("brain", context, speak, progress_cb))
        t1.start(); t2.start()
        t1.join(); t2.join()

        # Phase 3: Execution (A5)
        context = self.agents["executor"].run(context, speak)
        if progress_cb:
            progress_cb("executor", "completed")

        # Phase 4: Validation (A6)
        context = self.agents["validator"].run(context, speak)
        if progress_cb:
            progress_cb("validator", "completed")

        self._current_context = context
        return context.final_output or "Task completed, sir."

    def _run_agent_safe(self, name: str, context: AgentContext,
                        speak: Callable | None, progress_cb: Callable | None):
        try:
            self.agents[name].run(context, speak)
        except Exception as e:
            context.status[name] = f"failed: {e}"
        if progress_cb:
            progress_cb(name, context.status.get(name, "completed"))


_manager = None
_manager_lock = threading.Lock()


def get_manager() -> AgentManager:
    global _manager
    with _manager_lock:
        if _manager is None:
            _manager = AgentManager()
    return _manager
