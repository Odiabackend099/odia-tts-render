import requests, sys, time

base = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"

print("Health...", end=" ", flush=True)
r = requests.get(f"{base}/health", timeout=10)
r.raise_for_status()
print("OK", r.json())

print("Speak...", end=" ", flush=True)
r = requests.get(f"{base}/speak", params={"text":"Hello from smoke"}, timeout=30)
r.raise_for_status()
ct = r.headers.get("Content-Type","")
assert "audio/mpeg" in ct, f"Unexpected content-type: {ct}"
print("OK", len(r.content), "bytes")

print("Agent (echo)...", end=" ", flush=True)
r = requests.post(f"{base}/agent", json={"message":"Hello"}, timeout=10)
r.raise_for_status()
print("OK", r.json())
