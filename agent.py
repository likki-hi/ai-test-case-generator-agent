"""The agent: a small, visible chain of actions around a local Ollama model.

Actions (in order):
  1. check_input        - Python: reject empty or very short input
  2. analyze + generate - LLM (ONE call): feature, conditions, assumptions, scenario
                          categories and the structured test cases
  3. select_scenarios   - Python: keep only supported scenario categories
  4. validate           - Python: check fields, remove duplicates, assign IDs
"""
import json
import re
from dataclasses import dataclass, field

from langchain_core.output_parsers import StrOutputParser
from langchain_core.messages import SystemMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_ollama import ChatOllama

from prompts import COMBINED_SYSTEM, build_combined_input
from test_case_generator import ValidationError, validate_analysis, validate_test_cases

MAX_RETRIES = 2


class LLMError(Exception):
    """The local model could not be reached or failed."""


@dataclass
class AgentResult:
    status: str                      # "ok" or "needs_clarification"
    analysis: dict = field(default_factory=dict)
    categories: list = field(default_factory=list)
    test_cases: list = field(default_factory=list)
    trace: list = field(default_factory=list)
    clarification: str = ""


def extract_json(text: str):
    """Parse JSON from model text, tolerating code fences and extra words."""
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
    raise ValidationError("The model returned text that is not valid JSON.")


class TestCaseAgent:
    __test__ = False  # stop pytest from collecting this class

    def __init__(self, model: str = "llama3.2", temperature: float = 0.2,
                 base_url: str | None = None):
        kwargs = {"model": model, "temperature": temperature, "format": "json",
                  "keep_alive": "30m", "num_ctx": 4096}
        if base_url:
            kwargs["base_url"] = base_url
        self.llm = ChatOllama(**kwargs)

    # ---- LangChain chain: prompt -> local model -> text ----
    def _ask(self, system_prompt: str, user_text: str):
        prompt = ChatPromptTemplate.from_messages(
            [SystemMessage(content=system_prompt), ("human", "{input}")])
        chain = prompt | self.llm | StrOutputParser()
        try:
            return chain.invoke({"input": user_text})
        except Exception as exc:  # connection refused, model not pulled, etc.
            raise LLMError(
                "Could not get a response from the local model. Make sure Ollama is running "
                "(`ollama serve`) and the model is installed (`ollama pull <model>`). "
                f"Details: {exc}") from exc

    def _ask_json(self, system_prompt: str, user_text: str, check):
        """Ask, parse and validate; retry safely if the output is invalid."""
        last_error = None
        for attempt in range(MAX_RETRIES + 1):
            hint = "" if attempt == 0 else (
                "\n\nYour previous answer was invalid (" + str(last_error) +
                "). Return ONLY valid JSON in the requested shape.")
            raw = self._ask(system_prompt, user_text + hint)
            try:
                return check(extract_json(raw))
            except ValidationError as exc:
                last_error = exc
        raise ValidationError(f"The model kept returning invalid output. Last problem: {last_error}")

    # ---- actions ----
    def run(self, requirement: str, force: bool = False, max_cases: int = 10) -> AgentResult:
        trace = []
        requirement = (requirement or "").strip()
        if not requirement:
            raise ValueError("Please enter a software requirement first.")
        trace.append("1. check_input: requirement received")

        if len(requirement.split()) < 4 and not force:
            return AgentResult("needs_clarification", trace=trace + ["Stopped: input too short"],
                               clarification="The requirement is very short. Which feature should be tested, "
                                             "and what should it do?")

        def check(data):
            analysis = validate_analysis(data)
            if not analysis["is_clear"] and not force:
                return analysis, []
            return analysis, validate_test_cases(data.get("test_cases"))

        analysis, cases = self._ask_json(COMBINED_SYSTEM,
                                         build_combined_input(requirement, max_cases), check)
        trace.append(f"2. analyze + generate (one model call): feature = {analysis['feature']}")

        if not analysis["is_clear"] and not force:
            question = analysis["clarification_question"] or "Please describe the feature in more detail."
            return AgentResult("needs_clarification", analysis=analysis,
                               trace=trace + ["Stopped: unclear requirement"], clarification=question)

        categories = analysis["scenario_categories"]
        trace.append("3. select_scenarios: " + ", ".join(categories))
        cases = cases[:max_cases]
        trace.append(f"4. validate: {len(cases)} valid test cases")
        return AgentResult("ok", analysis, categories, cases, trace)