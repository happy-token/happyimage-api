import json
from pathlib import Path

from fastapi.testclient import TestClient

from api.app import create_app
from services.seed_gallery_service import PINNED_CATEGORY_ITEM_IDS, seed_gallery_service


def test_seed_gallery_lists_filters_and_serves_images(tmp_path: Path, monkeypatch):
    images_dir = tmp_path / "images"
    images_dir.mkdir()
    image_path = images_dir / "sample.jpg"
    image_path.write_bytes(b"fake-image")
    index_file = tmp_path / "records" / "evolink_cases.json"
    index_file.parent.mkdir()
    index_file.write_text(
        json.dumps(
            [
                {
                    "id": "ecommerce-1-sample",
                    "case_no": 1,
                    "title": "Sample Product Ad",
                    "category": "ecommerce",
                    "source_url": "https://example.com/source",
                    "prompt": "Warm studio product photo",
                    "local_images": ["images/sample.jpg"],
                    "license": "CC0-1.0",
                    "watermark_status": "needs_review",
                    "tags": ["ecommerce", "product"],
                    "dimensions": [{"path": "images/sample.jpg", "width": 1024, "height": 1024}],
                },
                {
                    "id": "portrait-1-sample",
                    "case_no": 2,
                    "title": "Sample Portrait",
                    "category": "portrait",
                    "source_url": "https://example.com/portrait",
                    "prompt": "Moody portrait",
                    "local_images": ["images/sample.jpg"],
                    "license": "CC0-1.0",
                    "watermark_status": "suspected_from_prompt",
                    "tags": ["portrait"],
                },
                {
                    "id": "ecommerce-2-sample",
                    "case_no": 3,
                    "title": "Sample Catalog",
                    "category": "ecommerce",
                    "source_url": "https://example.com/catalog",
                    "prompt": "Clean product catalog",
                    "local_images": ["images/sample.jpg"],
                    "license": "CC0-1.0",
                    "watermark_status": "not_requested_in_prompt",
                    "tags": ["ecommerce", "catalog"],
                },
                {
                    "id": "ad-creative-1-sample",
                    "case_no": 4,
                    "title": "Sample Product Concept",
                    "category": "ad-creative",
                    "source_url": "https://example.com/ad",
                    "prompt": "Studio product concept",
                    "local_images": ["images/sample.jpg"],
                    "license": "CC0-1.0",
                    "watermark_status": "not_requested_in_prompt",
                    "tags": ["product", "studio"],
                },
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(seed_gallery_service, "index_file", index_file)
    monkeypatch.setattr(seed_gallery_service, "images_dir", images_dir)
    monkeypatch.setattr(seed_gallery_service, "candidate_root", tmp_path / "candidates")
    monkeypatch.setattr(seed_gallery_service, "_cache_signature", ())
    monkeypatch.setattr(seed_gallery_service, "_cache_items", [])

    client = TestClient(create_app())

    response = client.get("/api/seed-gallery?category=ecommerce-main-image&query=studio")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["id"] == "ecommerce-1-sample"
    assert payload["items"][0]["images"][0]["url"] == "/api/seed-gallery/images/sample.jpg"

    detail_response = client.get("/api/seed-gallery/ecommerce-1-sample")
    assert detail_response.status_code == 200
    assert detail_response.json()["item"]["prompt"] == "Warm studio product photo"

    related_response = client.get("/api/seed-gallery/ecommerce-1-sample/related?limit=2")
    assert related_response.status_code == 200
    related_payload = related_response.json()
    assert related_payload["total"] == 3
    assert related_payload["limit"] == 2
    assert related_payload["has_more"] is True
    assert [item["id"] for item in related_payload["items"]] == [
        "ecommerce-2-sample",
        "ad-creative-1-sample",
    ]

    missing_related_response = client.get("/api/seed-gallery/missing-case/related")
    assert missing_related_response.status_code == 200
    assert missing_related_response.json()["items"] == []

    image_response = client.get("/api/seed-gallery/images/sample.jpg")
    assert image_response.status_code == 200
    assert image_response.content == b"fake-image"

    traversal_response = client.get("/api/seed-gallery/images/%2e%2e/records/evolink_cases.json")
    assert traversal_response.status_code == 404

    missing_api_response = client.get("/api/seed-gallery/images/../records/evolink_cases.json")
    assert missing_api_response.status_code == 404


def test_seed_gallery_portrait_filter_prioritizes_pinned_portraits(tmp_path: Path, monkeypatch):
    images_dir = tmp_path / "images"
    images_dir.mkdir()
    image_path = images_dir / "sample.jpg"
    image_path.write_bytes(b"fake-image")
    index_file = tmp_path / "records" / "evolink_cases.json"
    index_file.parent.mkdir()
    pinned_id = PINNED_CATEGORY_ITEM_IDS["portrait"][0]
    index_file.write_text(
        json.dumps(
            [
                {
                    "id": "product-with-portrait-alias",
                    "title": "Premium Bottle Portrait Ad",
                    "category": "product",
                    "prompt": "Product photography for a bottle with a portrait model",
                    "local_images": ["images/sample.jpg"],
                    "tags": ["portrait", "commercial"],
                },
                {
                    "id": "portrait-source-but-animal-sculpture",
                    "title": "Creative Recycled Plastic Bag Sea Animal Sculpture",
                    "category": "portrait",
                    "prompt": "A sea animal sculpture made from recycled plastic bags",
                    "local_images": ["images/sample.jpg"],
                    "tags": ["fashion", "female-portrait", "poster"],
                },
                {
                    "id": pinned_id,
                    "title": "Pinned Fresh Portrait",
                    "category": "portrait",
                    "prompt": "Fresh outdoor portrait of a young woman",
                    "local_images": ["images/sample.jpg"],
                    "tags": ["portrait"],
                },
                {
                    "id": "regular-lifestyle-portrait",
                    "title": "Regular Lifestyle Portrait",
                    "category": "portrait",
                    "prompt": "Natural lifestyle portrait",
                    "local_images": ["images/sample.jpg"],
                    "tags": ["portrait"],
                },
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(seed_gallery_service, "index_file", index_file)
    monkeypatch.setattr(seed_gallery_service, "images_dir", images_dir)
    monkeypatch.setattr(seed_gallery_service, "candidate_root", tmp_path / "candidates")
    monkeypatch.setattr(seed_gallery_service, "_cache_signature", ())
    monkeypatch.setattr(seed_gallery_service, "_cache_items", [])

    client = TestClient(create_app())

    response = client.get("/api/seed-gallery?category=portrait&limit=3")
    assert response.status_code == 200
    payload = response.json()
    assert [item["id"] for item in payload["items"]] == [
        pinned_id,
        "regular-lifestyle-portrait",
    ]
    assert payload["total"] == 2
    assert payload["items"][0]["category"] == "portrait"

    facets_response = client.get("/api/seed-gallery/facets")
    assert facets_response.status_code == 200
    categories = facets_response.json()["categories"]
    assert list(categories.items())[:3] == [
        ("portrait", 2),
        ("product-photography", 1),
        ("animal-pet", 1),
    ]
