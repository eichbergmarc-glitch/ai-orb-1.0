"""LM Studio als Hauptmodell: Strom, Denkbloecke, Systemnachrichten (06.11.2026)."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from backend.orchestrator.providers.base_provider import ChatMessage
from backend.orchestrator.providers.openai_compatible_provider import OpenAICompatibleProvider

ANFRAGEN: list[dict] = []
ZUSTAND = {"ablehnen": False}


class _Server(BaseHTTPRequestHandler):
    def log_message(self, *args):  # noqa: D401 - still
        pass

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        ANFRAGEN.append(body)
        if ZUSTAND["ablehnen"] and "chat_template_kwargs" in body:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b'{"error":"unknown field chat_template_kwargs"}')
            return
        if "prompt" in body:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for c in ["Hallo ", "Marc."]:
                self.wfile.write(("data: " + json.dumps({"choices": [{"text": c}]}) + "\n\n").encode())
            self.wfile.write(b"data: [DONE]\n\n")
            return
        if not body.get("stream"):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({"choices": [{"message": {"content": "<think>x</think>Hallo."}}]}).encode())
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        stuecke = [{"reasoning_content": "hm"}] + [
            {"content": c} for c in ["<thi", "nk>geheim</th", "ink>\n\nHal", "lo Marc. ", "Gut."]
        ]
        for s in stuecke:
            self.wfile.write(("data: " + json.dumps({"choices": [{"delta": s}]}) + "\n\n").encode())
            self.wfile.flush()
            time.sleep(0.01)
        self.wfile.write(b"data: [DONE]\n\n")


def _provider(port: int, **extra) -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider({
        "engine": "lmstudio", "preset": "lmstudio", "model": "qwen/qwen3.5-9b",
        "base_url": f"http://127.0.0.1:{port}/v1", "thinking": False,
        "minimum_predict_tokens": 96, "timeout": 10, "first_token_timeout": 5, **extra,
    })


VERLAUF = [
    ChatMessage("system", "Grund"), ChatMessage("user", "hi"),
    ChatMessage("system", "Suchtreffer"), ChatMessage("user", "und?"),
]


def _mit_server(arbeit):
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Server)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        return asyncio.run(arbeit(server.server_address[1]))
    finally:
        server.shutdown()


def test_strom_liefert_stuecke_ohne_denkblock():
    async def arbeit(port):
        return [s async for s in _provider(port).chat_stream(VERLAUF, max_tokens=40)]

    stuecke = _mit_server(arbeit)
    assert len(stuecke) >= 2, "kein echter Strom"
    assert "".join(stuecke) == "Hallo Marc. Gut."
    gesendet = ANFRAGEN[-1]
    assert gesendet["stream"] is True
    assert gesendet["max_tokens"] == 96
    assert gesendet["chat_template_kwargs"] == {"enable_thinking": False}
    # Genau eine Systemnachricht, und zwar vorn - sonst bricht die Qwen-Vorlage ab.
    rollen = [m["role"] for m in gesendet["messages"]]
    assert rollen == ["system", "user"]
    assert "Suchtreffer" in gesendet["messages"][0]["content"]


def test_einfacher_aufruf_entfernt_denkblock():
    async def arbeit(port):
        return (await _provider(port).chat(VERLAUF)).text

    assert _mit_server(arbeit) == "Hallo."


def test_unbekannter_vorlagenschalter_wird_weggelassen():
    ZUSTAND["ablehnen"] = True
    try:
        async def arbeit(port):
            return "".join([s async for s in _provider(port).chat_stream(VERLAUF)])

        assert _mit_server(arbeit) == "Hallo Marc. Gut."
        assert "chat_template_kwargs" not in ANFRAGEN[-1]
    finally:
        ZUSTAND["ablehnen"] = False


def test_chatml_roh_mit_leerem_denkblock():
    """LM Studio ignoriert enable_thinking - deshalb die Vorlage selbst bauen."""

    async def arbeit(port):
        return [s async for s in _provider(port, prompt_format="chatml").chat_stream(VERLAUF)]

    assert "".join(_mit_server(arbeit)) == "Hallo Marc."
    gesendet = ANFRAGEN[-1]
    assert "messages" not in gesendet and "chat_template_kwargs" not in gesendet
    prompt = gesendet["prompt"]
    assert prompt.startswith("<|im_start|>system\nGrund\n\nSuchtreffer<|im_end|>")
    assert prompt.endswith("<|im_start|>assistant\n<think>\n\n</think>\n\n")
    assert "<|im_end|>" in gesendet["stop"]
