"""Product image static serving."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_media_image_endpoint(client):
    images_dir = ROOT / "data" / "images"
    if not images_dir.is_dir():
        return
    sample = next(images_dir.iterdir(), None)
    if sample is None:
        return
    resp = client.get(f"/media/images/{sample.name}")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/")
