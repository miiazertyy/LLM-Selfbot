"""Calls, for the panel: the voices there are, hearing one, how quick the free path's voice is, and Try a call.

Try a call is the whole call brain (app/voice/session.py) with the panel standing in for a platform: your
microphone is the other person, and its voice comes back to your speakers. Nothing reaches any platform, nothing is
remembered and nothing is counted against the day's calls. Like the practice LIVE (livedemo_routes.py) it speaks as
the persona being edited in Settings, with the call settings on screen, saved or not.
"""
import asyncio
import json

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response

from app.voice.audio import BRAIN_RATE
from app.voice.session import Adapter, CallSession, calls_cfg

router = APIRouter(tags=["calls"])

# What the panel may set for a try, on top of what is saved.
_ON_SCREEN = ("engine", "realtime_provider", "realtime_model", "realtime_voice", "speaker", "voice", "hear", "think",
              "speak")


def _pid(raw: str) -> str:
    from app.utils import personas
    raw = str(raw or "")
    return raw if personas.valid_id(raw) and personas.exists(raw) else ""


def _scope(pid: str):
    from app.utils import personas
    return personas.scope(pid or None)


@router.get("/api/calls/voices")
async def voices(persona: str = ""):
    from app.voice import voices as v
    with _scope(_pid(persona)):
        return await v.catalogue()


@router.post("/api/calls/preview")
async def preview(request: Request):
    """A WAV of a voice saying one line, for Hear it."""
    from app.voice import voices as v
    body = await request.json()
    engine = "realtime" if body.get("engine") == "realtime" else "own"
    provider = str(body.get("provider") or ("gemini" if engine == "realtime" else "same"))
    with _scope(_pid(body.get("persona"))):
        try:
            wav = await asyncio.wait_for(v.preview(engine, provider, str(body.get("voice") or ""),
                                                   model=str(body.get("model") or "")), 45)
        except asyncio.TimeoutError:
            raise HTTPException(status_code=504, detail="The voice took too long to answer.")
        except Exception as e:
            raise HTTPException(status_code=409, detail=str(e)[:300] or "That voice could not be heard.")
    return Response(content=wav, media_type="audio/wav", headers={"Cache-Control": "no-store"})


@router.post("/api/calls/speed")
async def speed(request: Request):
    """How long the free path's voice takes to say a sentence."""
    from app.voice import voices as v
    body = await request.json()
    with _scope(_pid(body.get("persona"))):
        calls = {**calls_cfg(), **{k: body[k] for k in _ON_SCREEN if k in body}}
        return await v.speed({"bot": {"calls": calls}})


@router.get("/api/calls/speaker-voices")
async def speaker_voices(provider: str = "", model: str = "", persona: str = ""):
    """One speaker's voices, for Its voice: a list, fetched from its provider, or typed when they cannot be listed."""
    from app.voice import speech
    with _scope(_pid(persona)):
        return await speech.voices(provider, model)


@router.get("/api/calls/local")
async def local_voice():
    """This computer's own voice: whether it can run here, what is fetched, and how far a fetch has got."""
    from app.voice import onboard
    return onboard.status()


@router.post("/api/calls/local/get")
async def local_voice_get(request: Request):
    from app.voice import onboard
    body = await request.json()
    try:
        return onboard.get(str(body.get("model") or ""))
    except (ValueError, RuntimeError) as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/api/calls/local/remove")
async def local_voice_remove(request: Request):
    from app.voice import onboard
    body = await request.json()
    return onboard.remove(str(body.get("model") or ""))


class PanelCall(Adapter):
    """The panel as the other end of a call: microphone in, speakers out."""
    platform = "panel"
    counts = False
    in_rate = BRAIN_RATE
    out_rate = 24000

    def __init__(self):
        self.mic = asyncio.Queue()
        self.open = True

    async def frames(self):
        while self.open:
            pcm = await self.mic.get()
            if pcm is None:
                return
            yield pcm

    async def hang_up(self) -> None:
        self.open = False
        self.mic.put_nowait(None)


@router.websocket("/api/calls/try")
async def try_a_call(ws: WebSocket):
    """Binary frames in: your microphone, 16-bit mono at 16 kHz. Binary frames out: its voice, 16-bit mono at
    24 kHz, sent as it would play. Text frames out: what is happening (state, a line said, being talked over, the
    end). Text in: {"t": "hangup"}."""
    await ws.accept()
    q = ws.query_params
    pid = _pid(q.get("persona", ""))
    call = PanelCall()
    outbox = asyncio.Queue()

    with _scope(pid):
        saved = calls_cfg()
        on_screen = {k: q[k] for k in _ON_SCREEN if q.get(k) is not None}
        calls = {**saved, **on_screen, "enabled": True, "remember": False}
        session = CallSession(call, uid="", name="a friend", cfg={"bot": {"calls": calls}},
                              log=lambda m: outbox.put_nowait({"t": "note", "text": str(m)}))
        session.listen(outbox.put_nowait)

        async def take_in():
            try:
                while True:
                    msg = await ws.receive()
                    if msg.get("type") == "websocket.disconnect":
                        break
                    if msg.get("bytes"):
                        call.mic.put_nowait(msg["bytes"])
                    elif msg.get("text"):
                        try:
                            said = json.loads(msg["text"])
                        except ValueError:
                            continue
                        if said.get("t") == "hangup":
                            session.hang_up()
            except (WebSocketDisconnect, RuntimeError):
                pass
            session.end("you hung up")
            call.mic.put_nowait(None)

        async def send_out():
            # Its voice at the pace it plays, a frame every 20 ms: the session reads "still speaking" off what is
            # left to play, so draining it any faster would end its turns early and break being talked over.
            loop = asyncio.get_running_loop()
            tick = loop.time()
            while True:
                while not outbox.empty():
                    await ws.send_text(json.dumps(outbox.get_nowait()))
                if session.playout.busy:
                    await ws.send_bytes(session.playout.read())
                tick += 0.02
                await asyncio.sleep(max(0.0, tick - loop.time()))

        reader = asyncio.ensure_future(take_in())
        sender = asyncio.ensure_future(send_out())
        await ws.send_text(json.dumps({"t": "ready", "rate": call.out_rate, "mic_rate": call.in_rate}))
        try:
            record = await session.run()
            while not outbox.empty():
                await ws.send_text(json.dumps(outbox.get_nowait()))
            await ws.send_text(json.dumps({"t": "done", "seconds": record["seconds"], "reason": record["reason"],
                                           "engine": record["engine"]}))
        except Exception as e:
            try:
                await ws.send_text(json.dumps({"t": "error", "text": str(e)[:300]}))
            except Exception:
                pass
        finally:
            reader.cancel()
            sender.cancel()
            try:
                await ws.close()
            except Exception:
                pass
