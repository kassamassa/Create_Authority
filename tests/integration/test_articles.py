def test_list_articles_empty(test_client):
    response = test_client.get("/articles")
    assert response.status_code == 200
    assert response.json() == []


def test_get_article_not_found(test_client):
    response = test_client.get("/articles/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


def test_create_and_fetch_article(test_client, staging_supabase, dummy_article):
    inserted = staging_supabase.table("articles").insert(dummy_article).execute()
    staging_supabase.created_article_ids.append(dummy_article["id"])
    assert inserted.data

    response = test_client.get(f"/articles/{dummy_article['id']}")
    assert response.status_code == 200
    assert response.json()["title"] == dummy_article["title"]
