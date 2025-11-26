from pathlib import Path

import pytest

from src.services.catalog import CatalogService


def test_catalog_loads_and_searches(tmp_path: Path):
    sample = tmp_path / "catalog.json"
    sample.write_text(
        """
[
  {"product_id": 1, "name": "Червона сукня", "size": "122", "color": "червоний", "price": 100, "photo_url": "x", "category": "dress"},
  {"product_id": 2, "name": "Базова футболка", "size": "140", "color": "білий", "price": 50, "photo_url": "y", "category": "t-shirt"}
]
""",
        encoding="utf-8",
    )

    catalog = CatalogService(path=sample)

    # Case-insensitive search by name
    matches = catalog.search("СУКНЯ")
    assert len(matches) == 1
    assert matches[0].product_id == 1

    # Search by category fallback
    tee_matches = catalog.search("t-shirt")
    assert len(tee_matches) == 1
    assert tee_matches[0].product_id == 2

    # Search by color
    color_matches = catalog.search("білий")
    assert len(color_matches) == 1
    assert color_matches[0].product_id == 2


def test_catalog_missing_file_raises(tmp_path: Path):
    missing = tmp_path / "absent.json"
    with pytest.raises(FileNotFoundError):
        CatalogService(path=missing)
