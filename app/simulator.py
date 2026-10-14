"""The "brain" of the Alexa+ simulator.

It plays the role Alexa+ would: an AI agent that is an MCP client of
FixTrail. It discovers FixTrail's tools over Streamable HTTP, follows the
FixTrail Agent Skill (skills/fixtrail/SKILL.md), and answers in short
spoken sentences.

Two modes, chosen with SIMULATOR_MODE in .env:
  * "bedrock" - a real AI model on Amazon Bedrock, via the Strands Agents SDK.
  * "offline" - no AI and no AWS: simple keyword rules pick the tool. Good for
                testing and for demos without an AWS account. The agent loop
                and the MCP calls are exactly the same; only the model differs.
"""

import json
import re
import threading
import uuid
from collections import OrderedDict
from pathlib import Path
from typing import Any

from strands import Agent
from strands.models import Model
from strands.tools.mcp import MCPClient

from app.config import settings

SKILL_PATH = Path(__file__).resolve().parent.parent / "skills" / "fixtrail" / "SKILL.md"

VOICE_RULES = (
    "You are simulating Alexa+, a voice assistant. Reply in one to three short "
    "spoken sentences, with no markdown, lists, or links."
)


def load_skill() -> str:
    """The SKILL.md instructions (without the frontmatter) become the system prompt."""
    text = SKILL_PATH.read_text(encoding="utf-8")
    body = text.split("---", 2)[2] if text.startswith("---") else text
    return f"{VOICE_RULES}\n\n{body.strip()}"


# --------------------------------------------------------- offline model

ROOMS = ["living room", "front door", "back door", "kitchen", "bathroom", "bedroom",
         "basement", "hallway", "laundry", "garage", "attic", "balcony"]
CONTACT_WORDS = {"called": "call", "phoned": "call", "rang": "call", "texted": "text",
                 "messaged": "text", "emailed": "email", "told": "in person", "spoke": "in person",
                 "talked": "in person"}
PROBLEM_WORDS = re.compile(
    r"\b(leak|leaking|broken|broke|not working|stopped working|won't|doesn't work|no heat|"
    r"no hot water|mold|mould|mice|mouse|rats?|roach(es)?|bugs?|pests?|clogged|flooding|"
    r"cracked|smell|sparking|dripping|stuck|jammed)\b")


def _clean(text: str) -> str:
    text = re.sub(r"^\s*(hey\s+)?alexa[,!.\s]*", "", text, flags=re.I).strip()
    return text.rstrip(".!?")


def _title_from(text: str) -> str:
    title = re.sub(r"^(my|the|our|a|an)\s+", "", _clean(text), flags=re.I)
    title = re.sub(r"\b(is|are|has|have)\s+(been\s+)?", "", title, count=1)
    # The room is stored separately as the location: "... in the bedroom" -> "..."
    rooms = "|".join(re.escape(room) for room in ROOMS)
    title = re.sub(rf"\s+(in|at|by|near) (the |my |our )?({rooms})$", "", title, flags=re.I)
    return (title[:1].upper() + title[1:])[:80] or "Repair issue"


def route(utterance: str) -> tuple[str, dict] | None:
    """Pick a FixTrail tool and its inputs from what the tenant said."""
    text = _clean(utterance)
    low = text.lower()
    if re.search(r"\b(is )?fixtrail (running|working|there)\b|\bping\b", low):
        return "ping", {}
    if "report" in low and re.search(r"\b(make|create|generate|get|need|send)\b", low):
        about = re.search(r"\b(?:for|about|on) (the |my )?(.+)$", low)
        return "generate_report", {"issue": about.group(2)} if about else {}
    if re.search(r"\bremind\b|\bfollow[ -]?up\b|\bnudge\b", low):
        return "send_follow_up", {"issue": text}
    if re.search(r"\bphotos?\b|\bpictures?\b|\bpics?\b", low):
        return "get_photo_upload_link", {"issue": text}
    for word, method in CONTACT_WORDS.items():
        if re.search(rf"\b{word}\b", low) and "landlord" in low:
            return "log_contact_attempt", {"issue": text, "method": method}
    # Questions about everything come before complaints about one thing:
    # "what's still broken?" must not be read as "it's still broken".
    if re.search(r"what('s| is)? still broken|open issues|what('s| is) broken|any (update|news)|"
                 r"what('s| is) (open|outstanding)|status", low):
        return "list_open_issues", {}
    if re.search(r"still (isn't|is not|not|broken|leaking)|broke again|isn't fixed|not fixed|"
                 r"didn't fix|came back|still doesn't", low):
        return "dispute_fix", {"issue": text, "reason": text}
    if re.search(r"\b(is|are|got|been) (fixed|repaired)\b|\bworking (again|now)\b|\bfixed\b", low):
        return "confirm_fixed", {"issue": text}
    if re.search(r"\bhistory\b|what('s| has)? happened|what happened", low):
        return "get_issue_history", {"issue": text}
    if PROBLEM_WORDS.search(low):
        location = next((room for room in ROOMS if room in low), "home")
        return "report_issue", {"title": _title_from(text), "location": location}
    return None


class OfflineModel(Model):
    """A stand-in for an AI model. It speaks Strands' model interface (the same
    streaming format as Amazon Bedrock), but decides with keyword rules."""

    HELP = ("I can help with repair problems. Try: the kitchen sink is leaking, "
            "what's still broken, or remind my landlord about the heater.")

    def __init__(self):
        self.config: dict[str, Any] = {"model_id": "offline-keywords"}

    def update_config(self, **model_config: Any) -> None:
        self.config.update(model_config)

    def get_config(self) -> dict[str, Any]:
        return self.config

    async def structured_output(self, output_model, prompt, system_prompt=None, **kwargs):
        raise NotImplementedError("The offline model doesn't do structured output.")
        yield  # pragma: no cover  (makes this an async generator)

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
        last = messages[-1]
        tool_results = [block["toolResult"] for block in last["content"] if "toolResult" in block]
        if tool_results:
            # The tool already wrote a speakable answer: read it back as-is.
            reply = " ".join(c["text"] for r in tool_results for c in r["content"] if "text" in c)
            for event in _text_events(reply or "Done."):
                yield event
            return

        said = " ".join(block["text"] for block in last["content"] if "text" in block)
        choice = route(said)
        available = {spec["name"] for spec in tool_specs or []}
        if choice is None or choice[0] not in available:
            for event in _text_events(self.HELP):
                yield event
            return
        name, args = choice
        yield {"messageStart": {"role": "assistant"}}
        yield {"contentBlockStart": {"start": {"toolUse": {"toolUseId": f"tool-{uuid.uuid4().hex[:8]}", "name": name}}}}
        yield {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(args)}}}}
        yield {"contentBlockStop": {}}
        yield {"messageStop": {"stopReason": "tool_use"}}


def _text_events(text: str):
    yield {"messageStart": {"role": "assistant"}}
    yield {"contentBlockDelta": {"delta": {"text": text}}}
    yield {"contentBlockStop": {}}
    yield {"messageStop": {"stopReason": "end_turn"}}


# ------------------------------------------------------------- the agent

def make_model() -> Model:
    if settings.simulator_mode == "bedrock":
        from strands.models import BedrockModel  # needs AWS credentials
        return BedrockModel(model_id=settings.bedrock_model_id, region_name=settings.aws_region,
                            temperature=0.2)
    return OfflineModel()


def mode_label() -> str:
    if settings.simulator_mode == "bedrock":
        return f"Amazon Bedrock ({settings.bedrock_model_id})"
    return "Offline mode (keyword rules, no AI)"


class Simulator:
    """Keeps each browser session's conversation so follow-up questions work."""

    MAX_SESSIONS = 50

    def __init__(self, mcp_url: str | None = None, model_factory=make_model):
        self.mcp_url = mcp_url or settings.simulator_mcp_url
        self.model_factory = model_factory
        self.system_prompt = load_skill()
        self._histories: OrderedDict[str, list] = OrderedDict()
        self._lock = threading.Lock()

    def ask(self, session_id: str, text: str) -> dict:
        """Run one turn. Returns the spoken reply and the tools that were called."""
        with self._lock:
            history = list(self._histories.get(session_id, []))
        start = len(history)  # the agent appends to this list, so remember where we began
        # A fresh MCP connection per turn, so a server restart never leaves a
        # stale session behind. Strands opens and closes it for us.
        client = MCPClient(url=self.mcp_url)
        agent = Agent(model=self.model_factory(), tools=[client], system_prompt=self.system_prompt,
                      messages=history, callback_handler=None)
        try:
            result = agent(text)
        finally:
            client.stop(None, None, None)
        new_messages = agent.messages[start:]
        tools = [block["toolUse"]["name"] for m in new_messages for block in m["content"] if "toolUse" in block]
        reply = " ".join(block["text"] for block in result.message["content"] if "text" in block).strip()
        with self._lock:
            self._histories[session_id] = agent.messages
            self._histories.move_to_end(session_id)
            while len(self._histories) > self.MAX_SESSIONS:
                self._histories.popitem(last=False)
        return {"reply": reply or "Sorry, I didn't catch that.", "tools": tools}

    def reset(self, session_id: str) -> None:
        with self._lock:
            self._histories.pop(session_id, None)
