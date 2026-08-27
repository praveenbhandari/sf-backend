import base64

from app.schemas import PHOTO_MAX_BYTES

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
    assert body["addresses"][0]["type"] == "Work"
    assert body["addresses"][0]["id"] > 0


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


def test_contact_supports_multiple_typed_addresses(client, payload):
    addresses = [
        {
            "type": "Home",
            "address": "12 Home St",
            "city": "London",
            "country": "UK",
        },
        {
            "type": "Work",
            "address": "1 Market St",
            "city": "San Francisco",
            "state": "CA",
            "postal_code": "94105",
            "country": "USA",
        },
        {"type": "Other", "address": "PO Box 42"},
    ]

    body = client.post(BASE, json={**payload, "addresses": addresses}).json()

    assert [item["type"] for item in body["addresses"]] == ["Home", "Work", "Other"]
    assert len({item["id"] for item in body["addresses"]}) == 3


def test_patch_replaces_the_address_collection(client, payload):
    contact_id = client.post(BASE, json=payload).json()["id"]

    response = client.patch(
        f"{BASE}/{contact_id}",
        json={"addresses": [{"type": "Home", "address": "New home"}]},
    )

    assert response.status_code == 200
    assert response.json()["addresses"] == [
        {
            "id": response.json()["addresses"][0]["id"],
            "type": "Home",
            "address": "New home",
            "city": None,
            "state": None,
            "postal_code": None,
            "country": None,
        }
    ]


def test_address_type_and_street_are_validated(client, payload):
    bad_type = client.post(
        BASE,
        json={**payload, "addresses": [{"type": "Vacation", "address": "Beach"}]},
    )
    missing_street = client.post(
        BASE,
        json={**payload, "email": "other@example.com", "addresses": [{"type": "Home"}]},
    )

    assert bad_type.status_code == 422
    assert missing_street.status_code == 422


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
    assert body["addresses"] == []


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
    oversized = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * PHOTO_MAX_BYTES).decode()
    assert client.post(BASE, json={**payload, "photo": oversized}).status_code == 422


def test_photo_rejects_an_empty_payload(client, payload):
    assert client.post(BASE, json={**payload, "photo": "data:image/png;base64,"}).status_code == 422


def test_photo_rejects_base64_that_is_not_image_data(client, payload):
    not_an_image = "data:image/png;base64," + base64.b64encode(b"hello world!").decode()
    assert client.post(BASE, json={**payload, "photo": not_an_image}).status_code == 422


def test_photo_rejects_bytes_that_contradict_the_declared_type(client, payload):
    png_bytes_labelled_jpeg = TINY_PNG.replace("data:image/png", "data:image/jpeg")
    assert client.post(BASE, json={**payload, "photo": png_bytes_labelled_jpeg}).status_code == 422


def test_photo_accepts_jpeg_and_webp(client, payload):
    jpeg = "data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8\xff" + b"\x00" * 16).decode()
    webp = "data:image/webp;base64," + base64.b64encode(b"RIFF" + b"\x00" * 4 + b"WEBP" + b"\x00" * 8).decode()

    assert client.post(BASE, json={**payload, "photo": jpeg}).status_code == 201
    assert client.post(BASE, json={**payload, "email": "b@example.com", "photo": webp}).status_code == 201


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


def test_startup_adds_a_missing_photo_column_to_an_existing_table(client):
    """A database written before `photo` existed must gain the column, not 500."""
    from sqlalchemy import inspect, text

    from app.database import engine, init_db

    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE contacts DROP COLUMN photo"))
    assert "photo" not in {c["name"] for c in inspect(engine).get_columns("contacts")}

    init_db()

    assert "photo" in {c["name"] for c in inspect(engine).get_columns("contacts")}
    assert client.post(BASE, json={"first_name": "A", "last_name": "B", "email": "up@example.com"}).status_code == 201


def test_startup_tolerates_a_racing_add_column(client):
    """Another worker may add the column after inspect; that must not abort startup."""
    from unittest.mock import patch

    from sqlalchemy import inspect
    from sqlalchemy.engine.reflection import Inspector

    from app.database import _add_missing_columns, engine

    real_get_columns = Inspector.get_columns

    def omit_photo(self, table_name, *args, **kwargs):
        return [c for c in real_get_columns(self, table_name, *args, **kwargs) if c["name"] != "photo"]

    with patch.object(Inspector, "get_columns", omit_photo):
        _add_missing_columns()

    assert "photo" in {c["name"] for c in inspect(engine).get_columns("contacts")}


def test_put_replaces_the_whole_address_set(client, payload):
    created = client.post(BASE, json=payload).json()
    old_ids = {item["id"] for item in created["addresses"]}
    response = client.put(
        f"{BASE}/{created['id']}",
        json={
            "first_name": "Ada",
            "last_name": "Lovelace",
            "email": "ada@example.com",
            "addresses": [{"type": "Other", "address": "Turin"}],
        },
    )
    assert response.status_code == 200
    body = response.json()["addresses"]
    assert [item["type"] for item in body] == ["Other"]
    assert old_ids.isdisjoint({item["id"] for item in body})


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


def test_is_duplicate_column_uses_postgres_sqlstate_not_generic_already_exists():
    from types import SimpleNamespace

    from app.database import _is_duplicate_column

    class Wrapped:
        def __init__(self, orig):
            self.orig = orig

    assert _is_duplicate_column(Wrapped(SimpleNamespace(sqlstate="42701", pgcode="42701")))
    assert not _is_duplicate_column(Wrapped(SimpleNamespace(sqlstate="42P07", pgcode="42P07")))
    assert _is_duplicate_column(Wrapped(Exception("duplicate column name: photo")))
    assert not _is_duplicate_column(Wrapped(Exception('relation "contacts" already exists')))
