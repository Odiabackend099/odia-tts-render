# server.py — ODIA TTS Production Server
import os, asyncio, tempfile, logging, json
from typing import Optional
from datetime import datetime

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import edge_tts

# ---------- Config ----------
ENV = os.getenv("ENV", "production")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
TTS_VOICE_DEFAULT = os.getenv("TTS_VOICE", "en-NG-EzinneNeural")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(levelname)s [%(asctime)s] %(message)s",
)
log = logging.getLogger("odia-tts")

app = FastAPI(
    title="ODIA TTS Server",
    description="Nigerian Voice AI Infrastructure",
    version="1.0.0"
)

# CORS (tighten allow_origins in production to your domains)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Lazy OpenAI client
_oai = None
def get_openai_client():
    global _oai
    if _oai is None and OPENAI_API_KEY:
        try:
            from openai import OpenAI
            _oai = OpenAI(api_key=OPENAI_API_KEY)
            log.info("✅ OpenAI client initialized")
        except Exception as e:
            log.error(f"❌ OpenAI init failed: {e}")
            _oai = False
    return _oai if _oai else None

# ---------- Models ----------
class AgentIn(BaseModel):
    message: Optional[str] = Field(None, description="User message")
    text: Optional[str] = Field(None, description="Alias for message")
    agent: Optional[str] = Field("lexi", description="Agent type")

class AgentOut(BaseModel):
    reply: str
    mode: str
    agent: str
    error: Optional[str] = None
    timestamp: str

# ---------- Middleware for logging ----------
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = datetime.now()
    response = await call_next(request)
    latency_ms = int((datetime.now() - start_time).total_seconds() * 1000)
    log_data = {
        "level": "INFO",
        "method": request.method,
        "path": request.url.path,
        "status": response.status_code,
        "latency_ms": latency_ms
    }
    log.info(json.dumps(log_data))
    return response

# ---------- Routes ----------
@app.get("/", response_class=JSONResponse)
def root():
    return {
        "service": "ODIA TTS Server",
        "status": "operational",
        "voice": TTS_VOICE_DEFAULT,
        "endpoints": {
            "health": "/health",
            "speak": "/speak?text=...&voice=...",
            "agent": "POST /agent",
            "speak-agent": "POST /speak-agent"
        }
    }

@app.head("/")
def head_root():
    return JSONResponse(content="", status_code=200)

@app.get("/health")
def health():
    openai_status = "not_configured"
    if OPENAI_API_KEY:
        client = get_openai_client()
        openai_status = "ready" if client else "failed"
    return {
        "status": "ok",
        "voice": TTS_VOICE_DEFAULT,
        "openai": openai_status,
        "environment": ENV,
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/speak")
async def speak(
    text: str = Query(..., min_length=1, max_length=5000, description="Text to speak"),
    voice: Optional[str] = Query(None, description="Edge voice name"),
    rate: Optional[str] = Query("+0%", description="Speech rate (+/-X%)"),
    volume: Optional[str] = Query("+0%", description="Volume level (+/-X%)"),
):
    voice_name = (voice or TTS_VOICE_DEFAULT).strip()
    rate = rate if rate and rate != "0%" else "+0%"
    volume = volume if volume and volume != "0%" else "+0%"
    try:
        with tempfile.NamedTemporaryFile(prefix="odia_", suffix=".mp3", delete=False) as tmp:
            tmp_path = tmp.name
        log.info(f"TTS: voice={voice_name}, text_len={len(text)}, rate={rate}, volume={volume}")
        communicate = edge_tts.Communicate(text=text, voice=voice_name, rate=rate, volume=volume)
        await communicate.save(tmp_path)
        headers = {
            "Cache-Control": "no-store",
            "Content-Disposition": 'inline; filename="speech.mp3"',
            "X-Voice": voice_name,
        }
        return FileResponse(tmp_path, media_type="audio/mpeg", headers=headers)
    except Exception as e:
        log.error(f"TTS failed: {e}")
        raise HTTPException(status_code=500, detail={"error": "TTS generation failed", "message": str(e)})

@app.post("/agent", response_model=AgentOut)
async def agent(body: AgentIn):
    user_msg = (body.message or body.text or "").strip()
    agent_type = body.agent or "lexi"
    if not user_msg:
        raise HTTPException(status_code=422, detail="Either 'message' or 'text' field is required")
    client = get_openai_client()
    error_msg = None
    if client:
        try:
            system_prompts = {
                "lexi": "You are Agent Lexi from ODIA.dev, Nigeria's WhatsApp business automation assistant. Be concise, warm, and helpful in Nigerian English.",
                "miss": "You are Agent MISS from Mudiame University. Provide clear academic support.",
                "atlas": "You are Agent Atlas, ODIA's luxury concierge. Be sophisticated and precise.",
                "legal": "You are Miss Legal, ODIA's legal assistant. Be accurate and professional."
            }
            system_content = system_prompts.get(agent_type, system_prompts["lexi"])
            from openai import APIConnectionError, RateLimitError
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": user_msg}
                ],
                temperature=0.7,
                max_tokens=200,
                timeout=10.0
            )
            reply = (resp.choices[0].message.content or "").strip()
            if not reply:
                raise ValueError("Empty response from OpenAI")
            return AgentOut(reply=reply, mode="ai", agent=agent_type, timestamp=datetime.utcnow().isoformat())
        except Exception as e:
            log.error(f"OpenAI error: {type(e).__name__}: {e}")
            error_msg = f"ai_error: {type(e).__name__}"
    else:
        error_msg = "openai_not_configured"
    return AgentOut(
        reply=user_msg,  # echo
        mode="echo",
        agent=agent_type,
        error=error_msg,
        timestamp=datetime.utcnow().isoformat()
    )

@app.post("/speak-agent")
async def speak_agent(body: AgentIn):
    agent_response = await agent(body)
    return await speak(text=agent_response.reply, voice=TTS_VOICE_DEFAULT)

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=False)
