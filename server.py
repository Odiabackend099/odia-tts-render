# server.py — ODIA TTS Production Server (FIXED)
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

# CORS for all frontends
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- OpenAI Client (FIXED - no proxies) ----------
_oai = None

def get_openai_client():
    global _oai
    if _oai is False:  # Already tried and failed
        return None
    if _oai is None and OPENAI_API_KEY:
        try:
            from openai import OpenAI
            # CRITICAL: Only pass api_key, nothing else
            _oai = OpenAI(api_key=OPENAI_API_KEY)
            log.info("✅ OpenAI client initialized successfully")
        except Exception as e:
            log.error(f"❌ OpenAI init failed: {e}")
            _oai = False  # Prevent retry
    return _oai

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

# ---------- Request Logging ----------
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = datetime.now()
    response = await call_next(request)
    latency_ms = int((datetime.now() - start_time).total_seconds() * 1000)
    log.info(json.dumps({
        "level": "INFO",
        "method": request.method,
        "path": request.url.path,
        "status": response.status_code,
        "latency_ms": latency_ms
    }))
    return response

# ---------- Routes ----------
@app.get("/")
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
    text: str = Query(..., min_length=1, max_length=5000),
    voice: Optional[str] = Query(None),
    rate: Optional[str] = Query(None),
    volume: Optional[str] = Query(None),
):
    """Generate MP3 using Edge TTS"""
    voice_name = (voice or TTS_VOICE_DEFAULT).strip()
    
    # Fix rate/volume format for Edge TTS
    if not rate or rate == "0%":
        rate = "+0%"
    if not volume or volume == "0%":
        volume = "+0%"
    
    try:
        # Create temp file
        with tempfile.NamedTemporaryFile(
            prefix="odia_", 
            suffix=".mp3", 
            delete=False
        ) as tmp:
            tmp_path = tmp.name
        
        log.info(f"TTS: voice={voice_name}, len={len(text)}")
        
        # Generate speech
        communicate = edge_tts.Communicate(
            text=text,
            voice=voice_name,
            rate=rate,
            volume=volume
        )
        await communicate.save(tmp_path)
        
        # Return audio file
        return FileResponse(
            tmp_path,
            media_type="audio/mpeg",
            headers={
                "Cache-Control": "no-store",
                "Content-Disposition": 'inline; filename="speech.mp3"'
            }
        )
        
    except Exception as e:
        log.error(f"TTS failed: {e}")
        raise HTTPException(500, detail=str(e))

@app.post("/agent", response_model=AgentOut)
async def agent(body: AgentIn):
    """AI agent with echo fallback"""
    user_msg = (body.message or body.text or "").strip()
    agent_type = body.agent or "lexi"
    
    if not user_msg:
        raise HTTPException(422, detail="'message' or 'text' required")
    
    # Try OpenAI
    client = get_openai_client()
    
    if client:
        try:
            system_prompts = {
                "lexi": "You are Agent Lexi from ODIA.dev, Nigeria's WhatsApp automation assistant. Be warm, concise, helpful.",
                "miss": "You are Agent MISS from Mudiame University. Provide clear academic support.",
                "atlas": "You are Agent Atlas, ODIA's luxury concierge. Be sophisticated.",
                "legal": "You are Miss Legal, ODIA's legal assistant. Be precise."
            }
            
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompts.get(agent_type, system_prompts["lexi"])},
                    {"role": "user", "content": user_msg}
                ],
                temperature=0.7,
                max_tokens=200
            )
            
            reply = response.choices[0].message.content.strip()
            
            return AgentOut(
                reply=reply,
                mode="ai",
                agent=agent_type,
                timestamp=datetime.utcnow().isoformat()
            )
            
        except Exception as e:
            log.error(f"OpenAI error: {e}")
            error_msg = str(e)[:100]
    else:
        error_msg = "openai_not_configured"
    
    # Fallback to echo
    return AgentOut(
        reply=f"[Echo] {user_msg}",
        mode="echo",
        agent=agent_type,
        error=error_msg,
        timestamp=datetime.utcnow().isoformat()
    )

@app.post("/speak-agent")
async def speak_agent(body: AgentIn):
    """Get AI response and return as audio"""
    agent_response = await agent(body)
    return await speak(text=agent_response.reply)

# ---------- Main ----------
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=False)