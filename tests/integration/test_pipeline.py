def test_monitor_health(test_client):
    response = test_client.get("/monitor/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_monitor_status_counts(test_client, staging_supabase, dummy_article):
    staging_supabase.table("articles").insert(dummy_article).execute()
    staging_supabase.created_article_ids.append(dummy_article["id"])

    response = test_client.get("/monitor/status")
    assert response.status_code == 200
    assert response.json().get("collected", 0) >= 1
