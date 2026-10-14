"""Tests for the Agent Skill and the Alexa+ simulator (Phase 6)."""

import re
import socket
import threading
import time

import pytest
import uvicorn
from fastapi.testclient import TestClient

from app import db, services, simulator, web
from app.config import settings
from app.main import app
from app.simulator import SKILL_PATH, Simulator, route


# ------------------------------------------------------------- the skill

def test_skill_follows_the_agent_skills_spec():
    text = SKILL_PATH.read_text(encoding="utf-8")
    front = re.match(r"^---\n(.*?)\n---\n", text, re.S).group(1)
    name = re.search(r"^name: (.+)$", front, re.M).group(1).strip()
    description = re.search(r"^description: (.+)$", front, re.M).group(1).strip()

    assert name == SKILL_PATH.parent.name  # must match the folder name
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name) and len(name) <= 64
    assert 0 < len(description) <= 1024
    assert len(text.splitlines()) < 500


def test_skill_mentions_every_fixtrail_tool():
    import asyncio
    from mcp import Client
    from app.mcp_tools import mcp

    async def names():
        async with Client(mcp) as client:
            return {t.name for t in (await client.list_tools()).tools}

    skill = SKILL_PATH.read_text(encoding="utf-8")
    missing = [n for n in asyncio.run(names()) if f"`{n}`" not in skill]
    assert missing == []


def test_skill_becomes_the_system_prompt():
    prompt = simulator.load_skill()
    assert prompt.startswith("You are simulating Alexa+")
    assert "Honesty rules" in prompt
    assert "name: fixtrail" not in prompt  # frontmatter stripped


# ------------------------------------------------------- offline routing

@pytest.mark.parametrize("said, tool", [
    ("Alexa, the kitchen sink is leaking", "report_issue"),
    ("the heater stopped working in the bedroom", "report_issue"),
    ("there are mice in the kitchen", "report_issue"),
    ("what's still broken?", "list_open_issues"),
    ("any update from my landlord?", "list_open_issues"),
    ("what happened with the heater?", "get_issue_history"),
    ("remind my landlord about the heater", "send_follow_up"),
    ("I called my landlord about the sink", "log_contact_attempt"),
    ("I texted my landlord yesterday about the heat", "log_contact_attempt"),
    ("the sink is fixed", "confirm_fixed"),
    ("the heater is still broken", "dispute_fix"),
    ("it broke again", "dispute_fix"),
    ("how do I add photos of the leak", "get_photo_upload_link"),
    ("make my repair report", "generate_report"),
    ("is FixTrail running?", "ping"),
])
def test_offline_routing(said, tool):
    assert route(said)[0] == tool


def test_offline_routing_inputs():
    assert route("the heater stopped working in the bedroom") == (
        "report_issue", {"title": "Heater stopped working", "location": "bedroom"})
    assert route("I texted my landlord about the heat")[1]["method"] == "text"
    assert route("make my repair report for the sink") == ("generate_report", {"issue": "sink"})
    assert route("tell me a joke") is None


# ------------------------------------- the full agent loop over real MCP

@pytest.fixture(scope="module")
def running_server():
    """Run FixTrail on a free port, like the real server. One server per test
    module, because the MCP session manager can only be started once per app."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}/mcp"
    server.should_exit = True
    thread.join(timeout=10)


@pytest.fixture
def live_server(running_server, tmp_path, monkeypatch):
    """Each test gets a fresh database (the server reads db.DEFAULT_PATH per request)."""
    monkeypatch.setattr(db, "DEFAULT_PATH", str(tmp_path / "sim.db"))
    monkeypatch.setattr(services, "RUN_IN_BACKGROUND", False)

    class NoMail:
        def send(self, to, subject, body, reply_to=None):
            return "<id@test>"
    monkeypatch.setattr(services, "mailer", NoMail())
    return running_server


def test_simulator_conversation_over_mcp(live_server):
    sim = Simulator(mcp_url=live_server)

    first = sim.ask("s1", "Alexa, the kitchen sink is leaking")
    assert first["tools"] == ["report_issue"]
    assert "logged kitchen sink leaking" in first["reply"]

    second = sim.ask("s1", "what's still broken?")
    assert second["tools"] == ["list_open_issues"]
    assert second["reply"].startswith("You have 1 open issue.")

    third = sim.ask("s1", "the sink is fixed")
    assert third["tools"] == ["confirm_fixed"]

    conn = db.connect()
    assert db.list_issues(conn)[0]["status"] == "closed"
    assert db.verify_chain(conn)["ok"]
    conn.close()


def test_simulator_without_a_matching_tool_explains_itself(live_server):
    result = Simulator(mcp_url=live_server).ask("s2", "tell me a joke")
    assert result["tools"] == []
    assert "repair problems" in result["reply"]


def test_simulator_keeps_separate_conversations(live_server):
    sim = Simulator(mcp_url=live_server)
    sim.ask("a", "the heater stopped working")
    sim.ask("b", "what's still broken?")
    assert len(sim._histories["a"]) == 4  # user, tool call, tool result, reply
    sim.reset("a")
    assert "a" not in sim._histories and "b" in sim._histories


# ------------------------------------------------------------ the page

class FakeSimulator:
    def __init__(self):
        self.calls = []

    def ask(self, session, text):
        self.calls.append((session, text))
        return {"reply": "Got it.", "tools": ["report_issue"]}

    def reset(self, session):
        self.calls.append((session, "RESET"))


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DEFAULT_PATH", str(tmp_path / "page.db"))
    fake = FakeSimulator()
    monkeypatch.setattr(web, "_simulator", fake)
    c = TestClient(app)
    c.fake = fake
    return c


def test_simulator_page_needs_login(client):
    assert client.get("/simulator", follow_redirects=False).status_code == 303
    assert client.post("/simulator/ask", json={"text": "hi"}).status_code == 401


def test_simulator_page_and_ask(client):
    client.post("/login", data={"passcode": settings.tenant_passcode, "next": "/"})
    page = client.get("/simulator")
    assert "simulates Alexa+" in page.text
    assert "Offline mode" in page.text
    assert "fixtrail_sim" in page.cookies

    answer = client.post("/simulator/ask", json={"text": "The sink is leaking"}).json()
    assert answer == {"reply": "Got it.", "tools": ["report_issue"]}
    assert client.fake.calls[-1][1] == "The sink is leaking"

    assert client.post("/simulator/ask", json={"text": "  "}).status_code == 400
    assert client.post("/simulator/reset").json() == {"ok": True}
