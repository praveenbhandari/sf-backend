BASE = "/api/v1/contacts"

TINY_PNG = (
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
    "AAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "sqlite"


def test_create_contact(client, payload):
    response = client.post(BASE, json=payload)
    assert response.status_code == 201
    body = response.json()
    assert body["id"] > 0
    assert body["email"] == "ada@example.com"
    assert body["full_name"] == "Ada Lovelace"
    assert body["created_at"] and body["updated_at"]


def test_create_requires_valid_email(client, payload):
    response = client.post(BASE, json={**payload, "email": "not-an-email"})
    assert response.status_code == 422


def test_create_requires_names(client, payload):
    response = client.post(BASE, json={**payload, "first_name": ""})
    assert response.status_code == 422


def test_duplicate_email_conflicts(client, payload):
    assert client.post(BASE, json=payload).status_code == 201
    response = client.post(BASE, json={**payload, "email": "ADA@example.com"})
    assert response.status_code == 409


def test_get_contact(client, payload):
    contact_id = client.post(BASE, json=payload).json()["id"]
    response = client.get(f"{BASE}/{contact_id}")
    assert response.status_code == 200
    assert response.json()["id"] == contact_id


def test_get_missing_contact_returns_404(client):
    assert client.get(f"{BASE}/9999").status_code == 404


def test_list_pagination_and_total(client, payload):
    for index in range(5):
        client.post(BASE, json={**payload, "email": f"user{index}@example.com"})

    response = client.get(BASE, params={"limit": 2, "offset": 2})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 5
    assert len(body["items"]) == 2
    assert body["limit"] == 2 and body["offset"] == 2


def test_list_search(client, payload):
    client.post(BASE, json=payload)
    client.post(
        BASE,
        json={**payload, "first_name": "Grace", "last_name": "Hopper", "email": "grace@example.com", "company": "US Navy"},
    )

    hits = client.get(BASE, params={"search": "hopper"}).json()
    assert hits["total"] == 1
    assert hits["items"][0]["last_name"] == "Hopper"

    by_company = client.get(BASE, params={"search": "navy"}).json()
    assert by_company["total"] == 1

    misses = client.get(BASE, params={"search": "nobody"}).json()
    assert misses["total"] == 0


def test_list_sorting(client, payload):
    client.post(BASE, json={**payload, "last_name": "Zhang", "email": "z@example.com"})
    client.post(BASE, json={**payload, "last_name": "Adams", "email": "a@example.com"})

    names = [
        item["last_name"]
        for item in client.get(BASE, params={"sort_by": "last_name", "order": "asc"}).json()["items"]
    ]
    assert names == ["Adams", "Zhang"]


def test_list_rejects_bad_sort_field(client):
    assert client.get(BASE, params={"sort_by": "; DROP TABLE contacts"}).status_code == 422


def test_patch_updates_only_sent_fields(client, payload):
    contact_id = client.post(BASE, json=payload).json()["id"]
    response = client.patch(f"{BASE}/{contact_id}", json={"phone": "+1-000-000-0000"})
    assert response.status_code == 200
    body = response.json()
    assert body["phone"] == "+1-000-000-0000"
    assert body["first_name"] == "Ada"
    assert body["company"] == "Analytical Engines"


def test_patch_duplicate_email_conflicts(client, payload):
    first = client.post(BASE, json=payload).json()["id"]
    client.post(BASE, json={**payload, "email": "grace@example.com"})
    response = client.patch(f"{BASE}/{first}", json={"email": "grace@example.com"})
    assert response.status_code == 409


def test_patch_same_email_is_allowed(client, payload):
    contact_id = client.post(BASE, json=payload).json()["id"]
    response = client.patch(f"{BASE}/{contact_id}", json={"email": payload["email"]})
    assert response.status_code == 200


def test_put_replaces_contact(client, payload):
    contact_id = client.post(BASE, json=payload).json()["id"]
    response = client.put(
        f"{BASE}/{contact_id}",
        json={"first_name": "Grace", "last_name": "Hopper", "email": "grace@example.com"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["full_name"] == "Grace Hopper"
    assert body["company"] is None  # omitted fields are cleared by PUT


def test_put_missing_contact_returns_404(client):
    response = client.put(
        f"{BASE}/9999",
        json={"first_name": "A", "last_name": "B", "email": "ab@example.com"},
    )
    assert response.status_code == 404


def test_delete_contact(client, payload):
    contact_id = client.post(BASE, json=payload).json()["id"]
    assert client.delete(f"{BASE}/{contact_id}").status_code == 204
    assert client.get(f"{BASE}/{contact_id}").status_code == 404
    assert client.delete(f"{BASE}/{contact_id}").status_code == 404


def test_root_lists_entrypoints(client):
    body = client.get("/").json()
    assert body["contacts"] == BASE


def test_create_with_photo_echoes_it_back(client, payload):
    response = client.post(BASE, json={**payload, "photo": TINY_PNG})
    assert response.status_code == 201
    assert response.json()["photo"] == TINY_PNG


def test_create_without_photo_defaults_to_null(client, payload):
    response = client.post(BASE, json=payload)
    assert response.status_code == 201
    assert response.json()["photo"] is None


def test_photo_rejects_unsupported_image_type(client, payload):
    gif = TINY_PNG.replace("data:image/png", "data:image/gif")
    assert client.post(BASE, json={**payload, "photo": gif}).status_code == 422


def test_photo_rejects_malformed_base64(client, payload):
    bad = "data:image/png;base64,this is not base64!!!"
    assert client.post(BASE, json={**payload, "photo": bad}).status_code == 422


def test_photo_rejects_oversized_image(client, payload):
    import base64

    oversized = "data:image/png;base64," + base64.b64encode(b"\x00" * (2 * 1024 * 1024 + 1)).decode()
    assert client.post(BASE, json={**payload, "photo": oversized}).status_code == 422


def test_put_omitting_photo_clears_it(client, payload):
    contact_id = client.post(BASE, json={**payload, "photo": TINY_PNG}).json()["id"]
    response = client.put(
        f"{BASE}/{contact_id}",
        json={"first_name": "Ada", "last_name": "Lovelace", "email": "ada@example.com"},
    )
    assert response.status_code == 200
    assert response.json()["photo"] is None


def test_patch_omitting_photo_preserves_it(client, payload):
    contact_id = client.post(BASE, json={**payload, "photo": TINY_PNG}).json()["id"]
    response = client.patch(f"{BASE}/{contact_id}", json={"job_title": "Chief Engineer"})
    assert response.status_code == 200
    assert response.json()["photo"] == TINY_PNG


def test_create_with_multiple_addresses(client, payload):
    addresses = [
        {"type": "Home", "city": "San Francisco", "state": "CA", "country": "USA"},
        {"type": "Work", "street": "1 Analytical Way", "city": "London", "country": "UK"},
    ]
    response = client.post(BASE, json={**payload, "addresses": addresses})
    assert response.status_code == 201
    body = response.json()["addresses"]
    assert [a["type"] for a in body] == ["Home", "Work"]
    assert all(a["id"] > 0 for a in body)


def test_create_with_no_addresses(client, payload):
    response = client.post(BASE, json={**payload, "addresses": []})
    assert response.status_code == 201
    assert response.json()["addresses"] == []


def test_address_rejects_unknown_type(client, payload):
    response = client.post(BASE, json={**payload, "addresses": [{"type": "Office"}]})
    assert response.status_code == 422


def test_two_addresses_of_the_same_type_are_allowed(client, payload):
    addresses = [{"type": "Home", "city": "SF"}, {"type": "Home", "city": "LA"}]
    response = client.post(BASE, json={**payload, "addresses": addresses})
    assert response.status_code == 201
    assert len(response.json()["addresses"]) == 2


def test_put_replaces_the_whole_address_set(client, payload):
    created = client.post(BASE, json=payload).json()
    old_ids = {a["id"] for a in created["addresses"]}
    response = client.put(
        f"{BASE}/{created['id']}",
        json={
            "first_name": "Ada",
            "last_name": "Lovelace",
            "email": "ada@example.com",
            "addresses": [{"type": "Other", "city": "Turin"}],
        },
    )
    assert response.status_code == 200
    body = response.json()["addresses"]
    assert [a["type"] for a in body] == ["Other"]
    assert old_ids.isdisjoint({a["id"] for a in body})


def test_patch_omitting_addresses_preserves_them(client, payload):
    contact_id = client.post(BASE, json=payload).json()["id"]
    response = client.patch(f"{BASE}/{contact_id}", json={"job_title": "Chief Engineer"})
    assert response.status_code == 200
    assert len(response.json()["addresses"]) == 1


def test_patch_with_empty_list_clears_addresses(client, payload):
    contact_id = client.post(BASE, json=payload).json()["id"]
    response = client.patch(f"{BASE}/{contact_id}", json={"addresses": []})
    assert response.status_code == 200
    assert response.json()["addresses"] == []


def test_deleting_a_contact_cascades_to_its_addresses(client, payload):
    from sqlalchemy import func, select

    from app.database import SessionLocal
    from app.models import Address

    contact_id = client.post(BASE, json=payload).json()["id"]
    with SessionLocal() as db:
        assert db.execute(select(func.count()).select_from(Address)).scalar_one() == 1

    assert client.delete(f"{BASE}/{contact_id}").status_code == 204
    with SessionLocal() as db:
        assert db.execute(select(func.count()).select_from(Address)).scalar_one() == 0
