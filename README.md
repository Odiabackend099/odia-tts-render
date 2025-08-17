# ODIA TTS — Render-ready service

Production-ready Text-to-Speech + simple Agent endpoint.

## Endpoints
- `GET /health` — service status
- `GET /speak?text=...&voice=en-NG-EzinneNeural` — returns MP3
- `POST /agent` — `{ "message": "..." }` → AI reply (uses `OPENAI_API_KEY`) or echo fallback
- `POST /speak-agent` — combines agent + speech (returns MP3)

## Local run
```bash
python -m venv .venv && . .venv/Scripts/activate  # Windows
pip install -r requirements.txt
uvicorn server:app --reload --port 8000
```

## Render
- Build: `pip install -r requirements.txt`
- Start: `uvicorn server:app --host 0.0.0.0 --port $PORT`
- Set env vars in dashboard:
  - `OPENAI_API_KEY` (required for AI mode)
  - optional: `TTS_VOICE`, `LOG_LEVEL`, `ENV`
