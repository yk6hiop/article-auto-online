from __future__ import annotations

from fastapi.testclient import TestClient

from online_app.app import app
from online_app.deployment_readiness import collect_deployment_readiness


def test_deployment_readiness_collects_required_items():
    result = collect_deployment_readiness()
    names = {item.name for item in result["items"]}

    assert "Procfile" in names
    assert "Dockerfile" in names
    assert ".dockerignore" in names
    assert "render.yaml" in names
    assert "requirements.txt" in names
    assert "env.example" in names
    assert "公開対象の秘密情報スキャン" in names
    assert "Gitリポジトリ" in names
    assert "ジョブDB保存先" in names
    assert "Geminiキー外出し" in names
    assert "WordPress認証外出し" in names
    assert "設定診断" in names
    assert result["errors"] >= 0


def test_deployment_readiness_routes_render():
    client = TestClient(app)

    html_response = client.get("/deployment-readiness")
    api_response = client.get("/api/deployment-readiness")

    assert html_response.status_code == 200
    assert "デプロイ準備チェック" in html_response.text
    assert api_response.status_code == 200
    assert "ready_for_deploy_smoke" in api_response.json()
