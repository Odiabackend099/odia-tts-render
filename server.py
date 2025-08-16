#!/usr/bin/env python3
import asyncio
import io
import json
import logging
import os
import time
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse, PlainTextResponse
from pydantic import BaseModel
import edge_tts

# Optional OpenAI agent (echo fallback if no key)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
DEFAULT_VOICE = os.getenv("DEFAULT_VOICE", "en-NG-EzinneNeural")

app = FastAPI(title="ODIA TTS", version="1.0.0")

# CORS (allow all origins by default; tighten if you have a specific frontend domain)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "HEAD", "OPTIONS"],
    allow_headers=["*"],
)

# Simple JSON logger
logger = logging.getLogger("uvicorn.error")

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.time()
    try:
        response = await call_next(request)
        latency_ms = int((time.time() - start) * 1000)
        logger.info(json.dumps({
            "level": "INFO",
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "latency_ms": latency_ms
        }))
        return response
    except Exception as e:
        latency_ms = int((time.time() - start) * 1000)
        logger.error(json.dumps({
            "level": "ERROR",
            "method": request.method,
            "path": request.url.path,
            "error": str(e),
            "latency_ms": latency_ms
        }))
        raise

# In-memory IP rate limit (token bucket-ish). Good enough for single-instance Render.
RATE_LIMIT_PER_MIN = int(os.getenv("RATE_LIMIT_PER_MIN", "60"))
_buckets = {}  # ip -> (tokens, last_ts)

def _allow(ip: str) -> bool:
    now = time.time()
    tokens, last = _buckets.get(ip, (RATE_LIMIT_PER_MIN, now))
    # Refill
    elapsed = now - last
    refill = elapsed * (RATE_LIMIT_PER_MIN / 60.0)
    tokens = min(RATE_LIMIT_PER_MIN, tokens + refill)
    if tokens < 1:
        _buckets[ip] = (tokens, now)
        return False
    _buckets[ip] = (tokens - 1, now)
    return True

def _normalize_percent(v: Optional[str], default="+0%") -> str:
    """
    Edge TTS expects strings like '+0%', '-5%', '+10%'.
    Accepts '0', '0%', '+0', '+0%', '-5', '-5%', '10', '10%' etc.
    """
    if not v or v.strip() == "":
        return default
    s = v.strip().replace("%%", "%")  # handle accidental double-encoding
    if s.endswith("%"):
        s = s[:-1]
    try:
        # allow floats but round to int as edge-tts expects int percents
        val = int(float(s))
    except ValueError:
        # As a last resort, if exactly '0%' return '+0%'
        return default
    sign = "+" if val >= 0 else ""
    return f"{sign}{val}%"
    
@app.get("/", response_class=PlainTextResponse)
async def root():
    return "ODIA TTS server"

@app.head("/")
async def head_root():
    return PlainTextResponse("", status_code=200)

@app.get("/health")
async def health():
    return {"status": "ok", "voice": DEFAULT_VOICE}

@app.head("/health")
async def health_head():
    return PlainTextResponse("", status_code=200)

@app.get("/speak")
async def speak(
    request: Request,
    text: str = Query(..., min_length=1, description="Text to synthesize"),
    voice: str = Query(DEFAULT_VOICE, description="Microsoft voice name (Edge TTS)"),
    rate: Optional[str] = Query(None, description="e.g. '+0%' or '-5%' (0 also ok)"),
    volume: Optional[str] = Query(None, description="e.g. '+0%' or '-5%' (0 also ok)"),
):
    client_ip = request.client.host if request.client else "unknown"
    if not _allow(client_ip):
        raise HTTPException(status_code=429, detail="Too Many Requests")
    # Normalize rate/volume to the exact format Edge TTS wants
    rate_fmt = _normalize_percent(rate, default="+0%")
    vol_fmt = _normalize_percent(volume, default="+0%")
    try:
        communicate = edge_tts.Communicate(text, voice=voice, rate=rate_fmt, volume=vol_fmt)
        # Gather audio chunks and return a proper MP3 stream
        mp3_buffer = io.BytesIO()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                mp3_buffer.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                pass  # ignore markers
        mp3_buffer.seek(0)
        headers = {
            "Cache-Control": "no-store",
            "Content-Disposition": 'inline; filename="speech.mp3"',
        }
        return StreamingResponse(mp3_buffer, media_type="audio/mpeg", headers=headers)
    except edge_tts.exceptions.NoAudioReceived as e:
        raise HTTPException(status_code=502, detail=f"Edge TTS returned no audio: {e}")
    except Exception as e:
        # Ensure we always return JSON, not a broken mp3
        raise HTTPException(status_code=500, detail=f"internal_error: {e}")

# ---- Agent (optional OpenAI) ----
class Msg(BaseModel):
    message: str
    apiKey: Optional[str] = None  # allow passing key in body (dev/testing)

@app.post("/agent")
async def agent(body: Msg, request: Request):
    client_ip = request.client.host if request.client else "unknown"
    if not _allow(client_ip):
        raise HTTPException(status_code=429, detail="Too Many Requests")

    user_msg = (body.message or "").strip()
    if not user_msg:
        raise HTTPException(status_code=400, detail="message required")

    api_key = (body.apiKey or OPENAI_API_KEY).strip()
    if not api_key:
        # Echo fallback if no key configured
        return {"reply": user_msg, "mode": "echo"}

    # Lazy import so the package isn't required if you only use echo
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "You are a concise helpful Nigerian customer support assistant."},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.6,
            max_tokens=300,
        )
        reply = (resp.choices[0].message.content or "").strip()
        return {"reply": reply, "mode": "openai"}
    except Exception as e:
        # Fallback to echo on any OpenAI error
        logger.error(json.dumps({"level": "ERROR", "path": "/agent", "error": str(e)}))
        return {"reply": user_msg, "mode": "echo", "error": "openai_failed"}
