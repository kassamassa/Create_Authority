import uuid


def _insert_article(staging_supabase, article):
    staging_supabase.table("articles").insert(article).execute()
    staging_supabase.created_article_ids.append(article["id"])


def test_get_articles_by_status(test_client, staging_supabase, dummy_article):
    collected_article = dict(dummy_article)
    _insert_article(staging_supabase, collected_article)

    processed_article = dict(dummy_article)
    processed_article["id"] = str(uuid.uuid4())
    processed_article["source_url"] = f"https://example.com/articles/{uuid.uuid4()}"
    processed_article["status"] = "processed"
    _insert_article(staging_supabase, processed_article)

    response = test_client.get("/articles", params={"status": "collected"})
    assert response.status_code == 200

    data = response.json()
    assert all(article["status"] == "collected" for article in data)
    assert any(article["id"] == collected_article["id"] for article in data)
    assert not any(article["id"] == processed_article["id"] for article in data)


def test_get_article_by_id(test_client, staging_supabase, dummy_article):
    _insert_article(staging_supabase, dummy_article)

    response = test_client.get(f"/articles/{dummy_article['id']}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == dummy_article["id"]
    assert body["title"] == dummy_article["title"]


def test_get_article_not_found(test_client, staging_supabase):
    fake_id = str(uuid.uuid4())

    response = test_client.get(f"/articles/{fake_id}")

    assert response.status_code == 404

    result = staging_supabase.table("articles").select("id").eq("id", fake_id).execute()
    assert result.data == []


def test_update_article_status(test_client, staging_supabase, dummy_article):
    _insert_article(staging_supabase, dummy_article)

    response = test_client.patch(
        f"/articles/{dummy_article['id']}/status",
        json={"status": "processing"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "processing"

    result = (
        staging_supabase.table("articles")
        .select("status")
        .eq("id", dummy_article["id"])
        .execute()
    )
    assert result.data[0]["status"] == "processing"
