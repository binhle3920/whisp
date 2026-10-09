from fastapi import FastAPI
from fastapi.testclient import TestClient

from whisp.landing import router


def test_landing_page_introduces_whisp() -> None:
    app = FastAPI()
    app.include_router(router)

    response = TestClient(app).get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "An AI layer between your inbox and you." in response.text
    assert 'href="/dashboard"' in response.text
