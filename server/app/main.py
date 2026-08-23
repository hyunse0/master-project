from fastapi import FastAPI

app = FastAPI(title="Data Access Copilot API")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
