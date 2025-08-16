# ODIA TTS – Render-ready

Minimal, production-safe TTS microservice with:
- `GET /health` (+ `HEAD`) – health check
- `GET /speak?text=...&voice=&rate=&volume=` – MP3 stream via Edge TTS
- `POST /agent` – OpenAI reply if `OPENAI_API_KEY` is set, else **echo**

## Deploy to Render

1. Fork/Push this repo to GitHub.
2. In Render → **New Web Service** → connect the repo.
3. Render will read `render.yaml`:
   - Build: `pip install -r requirements.txt`
   - Start: `uvicorn server:app --host 0.0.0.0 --port $PORT`
4. Set environment variables (in Render dashboard):
   - `OPENAI_API_KEY` (optional)
   - `DEFAULT_VOICE` (optional, default `en-NG-EzinneNeural`)
   - `RATE_LIMIT_PER_MIN` (optional, default `60`)

## Local run

```bash
python -m venv .venv
.\.venv\Scripts\activate   # Windows
pip install -r requirements.txt
set PORT=8000
uvicorn server:app --host 0.0.0.0 --port %PORT%
```

### Quick test
```bash
curl http://127.0.0.1:8000/health
curl -s -L "http://127.0.0.1:8000/speak?text=Hello%20from%20ODIA%20TTS" -o hello.mp3
```

If you pass `rate=0%` or `volume=0%`, the server normalizes to `+0%` (Edge TTS format).  
Examples:
```
/speak?text=Hi&rate=0%&volume=-5%&voice=en-NG-EzinneNeural
```

## /agent (optional)
```bash
curl -X POST http://127.0.0.1:8000/agent -H "Content-Type: application/json" -d "{\"message\":\"Hello\"}"
# => echoes "Hello" when OPENAI_API_KEY is not set
```

With OpenAI:
```bash
set OPENAI_API_KEY=sk-...  # or set it in Render's env vars
curl -X POST http://127.0.0.1:8000/agent -H "Content-Type: application/json" -d "{\"message\":\"Hello\"}"
# => model reply
```

## Notes
- CORS is open by default so any frontend (Vite/Lovable/Next) can call it.
- Returns **audio/mpeg** for `/speak`. We stream a real MP3, not JSON.
- On errors we return JSON (never a broken MP3 file).

## License
MIT
