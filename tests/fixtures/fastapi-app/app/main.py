from fastapi import FastAPI

app = FastAPI()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/score")
def score(payload: dict) -> dict:
    text = str(payload.get("text", ""))
    return {"score": len(text)}
