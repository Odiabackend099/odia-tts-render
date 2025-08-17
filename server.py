# server.py - Odiadev TTS (Fixed)
import os, asyncio, tempfile, logging, json, re
from typing import Optional
from datetime import datetime
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import edge_tts

ENV = os.getenv("ENV", "production")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
TTS_VOICE_DEFAULT = os.getenv("TTS_VOICE", "en-NG-EzinneNeural")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()

logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO), format="%(levelname)s [%(asctime)s] %(message)s")
log = logging.getLogger("odiadev")

app = FastAPI(title="Odiadev TTS", description="Voice AI by odia.dev", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

def clean_text_for_tts(text: str) -> str:
    text = re.sub(r'[^\x00-\x7F]+', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

_oai = None
def get_openai_client():
    global _oai
    if _oai is False: return None
    if _oai is None and OPENAI_API_KEY:
        try:
            from openai import OpenAI
            _oai = OpenAI(api_key=OPENAI_API_KEY)
            log.info("OpenAI ready")
        except Exception as e:
            log.error(f"OpenAI failed: {e}")
            _oai = False
    return _oai

class AgentIn(BaseModel):
    message: Optional[str] = None
    text: Optional[str] = None
    agent: Optional[str] = "lexi"

class AgentOut(BaseModel):
    reply: str
    mode: str
    agent: str
    error: Optional[str] = None
    timestamp: str

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = datetime.now()
    response = await call_next(request)
    latency_ms = int((datetime.now() - start_time).total_seconds() * 1000)
    log.info(json.dumps({"method": request.method, "path": request.url.path, "status": response.status_code, "latency_ms": latency_ms}))
    return response

@app.get("/")
def root():
    return {"service": "Odiadev TTS", "company": "Odiadev", "website": "https://odia.dev", "status": "operational", "voice": TTS_VOICE_DEFAULT}

@app.head("/")
def head_root():
    return JSONResponse(content="", status_code=200)

@app.get("/health")
def health():
    openai_status = "not_configured"
    if OPENAI_API_KEY:
        client = get_openai_client()
        openai_status = "ready" if client else "failed"
    return {"status": "ok", "service": "Odiadev TTS", "voice": TTS_VOICE_DEFAULT, "openai": openai_status, "company": "Odiadev"}

@app.get("/speak")
async def speak(text: str = Query(..., min_length=1, max_length=5000), voice: Optional[str] = None, rate: Optional[str] = None, volume: Optional[str] = None):
    text = clean_text_for_tts(text)
    if not text: raise HTTPException(400, detail="Empty text")
    voice_name = (voice or TTS_VOICE_DEFAULT).strip()
    if not rate or rate == "0%": rate = "+0%"
    if not volume or volume == "0%": volume = "+0%"
    try:
        with tempfile.NamedTemporaryFile(prefix="odiadev_", suffix=".mp3", delete=False) as tmp:
            tmp_path = tmp.name
        communicate = edge_tts.Communicate(text=text, voice=voice_name, rate=rate, volume=volume)
        await communicate.save(tmp_path)
        return FileResponse(tmp_path, media_type="audio/mpeg", headers={"Cache-Control": "public, max-age=3600", "Content-Disposition": 'inline; filename="speech.mp3"'})
    except Exception as e:
        log.error(f"TTS failed: {e}")
        raise HTTPException(500, detail=str(e))

@app.post("/agent", response_model=AgentOut)
async def agent(body: AgentIn):
    user_msg = (body.message or body.text or "").strip()
    agent_type = body.agent or "lexi"
    if not user_msg: raise HTTPException(422, detail="Message required")
    client = get_openai_client()
    if client:
        try:
            prompts = {
                "lexi": "You are Lexi from odia.dev, Nigeria's WhatsApp automation assistant. Be helpful and concise. Never use emojis.",
                "miss": "You are MISS from Mudiame University. Provide academic support. Never use emojis.",
                "atlas": "You are Atlas, Odiadev's luxury concierge. Be sophisticated. Never use emojis.",
                "legal": "You are Miss Legal, Odiadev's legal assistant. Be professional. Never use emojis."
            }
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "system", "content": prompts.get(agent_type, prompts["lexi"])}, {"role": "user", "content": user_msg}],
                temperature=0.7, max_tokens=250
            )
            reply = clean_text_for_tts(response.choices[0].message.content.strip())
            return AgentOut(reply=reply, mode="ai", agent=agent_type, timestamp=datetime.utcnow().isoformat())
        except Exception as e:
            log.error(f"OpenAI error: {e}")
            error_msg = str(e)[:100]
    else:
        error_msg = "openai_not_configured"
    return AgentOut(reply=f"[Echo]: {user_msg}", mode="echo", agent=agent_type, error=error_msg, timestamp=datetime.utcnow().isoformat())

@app.post("/speak-agent")
async def speak_agent(body: AgentIn):
    agent_response = await agent(body)
    return await speak(text=agent_response.reply)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")), reload=False)
