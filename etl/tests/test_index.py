"""Documentos de Meilisearch: campos del buscador y de los filtros del catálogo."""

from decimal import Decimal

from etl import index


def _row(**over):
    row = {
        "id": "1",
        "name_es": "Pechuga de pollo",
        "name_en": None,
        "brand": None,
        "kind": "generic",
        "category": None,
        "quality_rank": 4,
        "source": "bedca",
        "nutriscore_grade": None,
        "nova_group": None,
        "ecoscore_grade": None,
        "kcal_100g": Decimal("110"),
        "protein_100g": Decimal("23"),
        "fat_100g": Decimal("1.5"),
        "carbs_100g": Decimal("0"),
        "saturated_100g": None,
        "sugars_100g": None,
        "fiber_100g": None,
        "salt_100g": None,
        "has_image": False,
    }
    row.update(over)
    return row


def test_generic_food_gets_type_and_nutrition_tags_but_no_supermarket():
    doc = index.build_document(_row())
    assert doc["supermarket"] is None
    assert doc["food_group"] == "meat"
    assert {"high_protein", "low_fat", "low_carb"} <= set(doc["nutrition_tags"])
    assert doc["kcal_100g"] == 110.0 and doc["fat_100g"] == 1.5


def test_store_brand_product_gets_its_supermarket_and_score_tags():
    doc = index.build_document(
        _row(
            name_es="Yogur natural",
            brand="Hacendado, MERCADONA",
            kind="branded",
            source="off",
            nutriscore_grade="a",
            nova_group=1,
            sugars_100g=Decimal("4"),
        )
    )
    assert doc["supermarket"] == "mercadona"
    assert doc["food_group"] == "dairy"
    assert {"nutriscore_ab", "minimally_processed", "low_sugar"} <= set(doc["nutrition_tags"])


def test_unknown_data_never_produces_a_tag():
    doc = index.build_document(_row(sugars_100g=None, fiber_100g=None, salt_100g=None))
    assert not {"low_sugar", "sugar_free", "high_fiber", "low_salt"} & set(doc["nutrition_tags"])


def test_filterable_attributes_cover_the_document_filter_fields():
    filterable = set(index.INDEX_SETTINGS["filterableAttributes"])
    assert {"source", "supermarket", "food_group", "nutrition_tags"} <= filterable
    assert "protein_100g" in index.INDEX_SETTINGS["sortableAttributes"]


def test_result_totals_are_not_capped_at_one_thousand():
    assert index.INDEX_SETTINGS["pagination"]["maxTotalHits"] >= 25000
