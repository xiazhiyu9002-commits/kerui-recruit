from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(title="KeRui Recruit", version="0.1.0")

    @app.get("/health/live")
    def live() -> dict[str, str]:
        return {"status": "alive"}

    return app
