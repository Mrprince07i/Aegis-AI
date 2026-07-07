import json
import re
import sys
import threading
from pathlib import Path
from typing import Any, Callable


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR        = get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"


class AgentContext:
    """Shared context passed between agents in a pipeline."""
    def __init__(self, goal: str = ""):
        self.goal: str = goal
        self.plan: list[dict] = []
        self.research: list[str] = []
        self.memory: list[str] = []
        self.execution_results: list[str] = []
        self.final_output: str = ""
        self.errors: list[str] = []
        self.status: dict[str, str] = {}  # agent_name -> status


class BaseAgent:
    """Base class for all specialized agents."""

    def __init__(self, name: str, role: str, system_prompt: str,
                 model: str = "gemini-2.5-flash-lite"):
        self.name = name
        self.role = role
        self.system_prompt = system_prompt
        self.model_name = model
        self._llm = None

    def _get_api_key(self) -> str:
        with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)["gemini_api_key"]

    def _get_llm(self):
        if self._llm is None:
            import google.generativeai as genai
            genai.configure(api_key=self._get_api_key())
            self._llm = genai.GenerativeModel(
                model_name=self.model_name,
                system_instruction=self.system_prompt
            )
        return self._llm

    def run(self, context: AgentContext, speak: Callable | None = None) -> AgentContext:
        """Run this agent and update context. Override in subclasses."""
        raise NotImplementedError

    def _ask_llm(self, prompt: str) -> str:
        try:
            response = self._get_llm().generate_content(prompt)
            return response.text.strip()
        except Exception as e:
            return f"[{self.name} LLM error: {e}]"

    def _extract_json(self, text: str) -> dict:
        text = re.sub(r"```(?:json)?", "", text).strip().rstrip("`").strip()
        return json.loads(text)
