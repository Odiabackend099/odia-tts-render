# server.py — ODIA TTS (Render-ready)
import os, asyncio, tempfile, logging
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

import edge_tts
from openai import OpenAI

# ---------- Config ----------
ENV = os.getenv("ENV", "production")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
TTS_VOICE_DEFAULT = os.getenv("TTS_VOICE", "en-NG-EzinneNeural")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(levelname)s [%(asctime)s] %(message)s",
)
log = logging.getLogger("odia-tts")

app = FastAPI(title="ODIA TTS server")

# OpenAI client (created only if key exists)
_oai: Optional[OpenAI] = None
if OPENAI_API_KEY:
    try:
        _oai = OpenAI(api_key=OPENAI_API_KEY)
        log.info("OpenAI client initialized")
    except Exception as e:
        log.exception("Failed to init OpenAI: %s", e)
else:
    log.warning("OPENAI_API_KEY not set: /agent will run in 'echo' mode")

# ---------- Models ----------
class AgentIn(BaseModel):
    # accept either "message" (preferred) or "text" for flexibility
    message: Optional[str] = Field(None, description="User message")
    text:    Optional[str] = Field(None, description="Alias of message")

class AgentOut(BaseModel):
    reply: str
    mode: str
    error: Optional[str] = None

# ---------- Routes ----------
@app.get("/", response_class=PlainTextResponse)
def root():
    return "ODIA TTS server"

@app.get("/health")
def health():
    return {"status": "ok", "voice": TTS_VOICE_DEFAULT}

@app.get("/speak")
async def speak(
    text: str = Query(..., min_length=1, description="Text to speak"),
    voice: Optional[str] = Query(None, description="Edge voice name"),
):
    """
    Generate MP3 using Microsoft Edge TTS and return it inline.
    """
    voice_name = (voice or TTS_VOICE_DEFAULT).strip()
    if not voice_name:
        voice_name = "en-NG-EzinneNeural"

    # generate into a temp file then return it
    try:
        tmp = tempfile.NamedTemporaryFile(prefix="odia_", suffix=".mp3", delete=False)
        tmp_path = tmp.name
        tmp.close()

        log.info("TTS voice=%s text_len=%d", voice_name, len(text))
        communicate = edge_tts.Communicate(text=text, voice=voice_name)
        await communicate.save(tmp_path)

        headers = {
            "Cache-Control": "no-store",
            "content-disposition": 'inline; filename="speech.mp3"',
        }
        return FileResponse(tmp_path, media_type="audio/mpeg", headers=headers)
    except Exception as e:
        log.exception("TTS failed: %s", e)
        raise HTTPException(status_code=500, detail="TTS generation failed")

@app.post("/agent", response_model=AgentOut)
def agent(body: AgentIn):
    """
    Lightweight agent: calls OpenAI when key is present; otherwise echoes.
    """
    user_msg = (body.message or body.text or "").strip()
    if not user_msg:
        # FastAPI will already return 422, but be explicit:
        raise HTTPException(status_code=422, detail="Field 'message' or 'text' is required")

    # Echo fallback when key missing OR client init failed
    if not _oai:
        return AgentOut(reply=user_msg, mode="echo", error="openai_not_configured")

    try:
        # Use a stable, inexpensive model
        resp = _oai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are Lexi, a friendly Nigerian voice AI assistant."},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.6,
            max_tokens=180,
        )
        reply = (resp.choices[0].message.content or "").strip()
        if not reply:
            raise RuntimeError("Empty reply from OpenAI")
        return AgentOut(reply=reply, mode="ai")
    except Exception as e:
        # Don’t crash; surface the reason and return echo so the UX still works.
        err = f"openai_failed: {type(e).__name__}"
        log.exception("OpenAI error: %s", e)
        return AgentOut(reply=user_msg, mode="echo", error=err)

# ---------- Local dev run ----------
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("server:app", host="0.0.0.0", port=port)
