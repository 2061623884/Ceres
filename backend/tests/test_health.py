"""Health endpoint tests."""

def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "llm_mode" in data
    assert "openai" not in str(data).lower() or "api_key" not in str(data).lower()


def test_bootstrap(client):
    resp = client.get("/api/v1/bootstrap")
    assert resp.status_code == 200
    data = resp.json()
    assert data["business_data_mode"] == "demo"
    assert "demo_notice" in data


def test_health_reports_missing_retrieval_without_network(client, monkeypatch):
    from app.core.config import get_settings
    monkeypatch.setenv('RETRIEVAL_INDEX_DIR', '')
    get_settings.cache_clear()
    result = client.get('/health').json()['retrieval']
    assert result['status'] == 'unavailable'
    assert result['reason'] == 'RETRIEVAL_NOT_CONFIGURED'
    assert result['remote_checked'] is False
