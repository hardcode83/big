from fastapi import FastAPI

app = FastAPI(title="AutoHostAI backend")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
