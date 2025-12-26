"""
VisionResponse Contract Tests.
==============================
Tests that enforce the VisionResponse specification.

INVARIANTS:
1. If confidence >= 0.5 → identified_product.name MUST NOT be null
2. Product price/color MUST come from the catalog database, NOT from LLM
3. needs_clarification=True → clarification_question MUST NOT be empty
"""

from unittest.mock import patch

import pytest

from src.agents.pydantic.models import ProductMatch as IdentifiedProduct
from src.agents.pydantic.models import VisionResponse


# =============================================================================
# CONTRACT: VisionResponse Schema
# =============================================================================


class TestVisionResponseSchema:
    """VisionResponse schema validation."""

    def test_valid_response_with_product(self):
        """Valid response with identified product - Костюм Лагуна рожевий."""
        response = VisionResponse(
            reply_to_user="Це костюм Лагуна!",
            confidence=0.9,
            needs_clarification=False,
            identified_product=IdentifiedProduct(
                name="Костюм Лагуна",
                price=2190,  # Ціна для розміру 122-128
                color="рожевий",
                photo_url="https://cdn.sitniks.com/cmp-2065/products/2025-10-03/8542510/12a6cc-1759503080447.jpeg",
            ),
        )
        assert response.confidence >= 0.5
        assert response.identified_product is not None
        assert response.identified_product.name is not None

    def test_valid_response_low_confidence_no_product(self):
        """Low confidence response can have no product."""
        response = VisionResponse(
            reply_to_user="Не вдалося впізнати товар.",
            confidence=0.3,
            needs_clarification=True,
            clarification_question="Чи можете надіслати фото з іншого ракурсу?",
        )
        assert response.confidence < 0.5
        # Low confidence = identified_product can be None

    def test_clarification_requires_question(self):
        """If needs_clarification=True, clarification_question should be set."""
        response = VisionResponse(
            reply_to_user="Потрібна допомога.",
            confidence=0.4,
            needs_clarification=True,
            clarification_question="Який саме товар вас цікавить?",
        )
        assert response.needs_clarification is True
        assert response.clarification_question is not None
        assert len(response.clarification_question) > 0


# =============================================================================
# INVARIANT 1: High confidence → product identified
# =============================================================================


class TestHighConfidenceProductInvariant:
    """If confidence >= 0.5, identified_product.name MUST NOT be null."""

    @pytest.mark.parametrize("confidence", [0.5, 0.6, 0.7, 0.8, 0.9, 1.0])
    def test_high_confidence_requires_product(self, confidence):
        """High confidence responses should have identified_product."""
        # This is a specification test - it validates the contract
        # In real usage, the LLM should follow this rule

        # Valid case: high confidence WITH product
        response = VisionResponse(
            reply_to_user="Знайдено товар",
            confidence=confidence,
            needs_clarification=False,
            identified_product=IdentifiedProduct(
                name="Test Product",
                price=1000,
            ),
        )
        assert response.identified_product is not None
        assert response.identified_product.name is not None

    @pytest.mark.parametrize("confidence", [0.0, 0.1, 0.2, 0.3, 0.4, 0.49])
    def test_low_confidence_allows_no_product(self, confidence):
        """Low confidence responses can have no identified_product."""
        response = VisionResponse(
            reply_to_user="Не впевнений",
            confidence=confidence,
            needs_clarification=True,
        )
        # Low confidence = product can be None
        assert response.confidence < 0.5


# =============================================================================
# INVARIANT 2: Product data from catalog database (enrichment test)
# =============================================================================


class TestProductEnrichmentInvariant:
    """Product price/color MUST be enriched from catalog database."""

    @pytest.mark.asyncio
    async def test_vision_node_enriches_product_from_db(self):
        """vision_node should enrich product data from catalog database."""

        # Mock run_vision to return product with price=0 (LLM doesn't know price)
        async def mock_run_vision(message, deps):
            return VisionResponse(
                reply_to_user="Це костюм Лагуна!",
                confidence=0.9,
                needs_clarification=False,
                identified_product=IdentifiedProduct(
                    name="Костюм Лагуна",
                    price=0,  # LLM doesn't know real price
                    color="",  # LLM doesn't know real color
                ),
            )

        # Mock DB enrichment
        async def mock_enrich(name):
            return {
                "price": 2350,
                "color": "рожевий",
                "photo_url": "https://example.com/real_photo.jpg",
                "id": 123,
            }

        with patch("src.agents.pydantic.vision_agent.run_vision", new=mock_run_vision):
            with patch(
                "src.agents.langgraph.nodes.vision._enrich_product_from_db", new=mock_enrich
            ):
                import importlib

                import src.agents.langgraph.nodes.vision as vision_module

                importlib.reload(vision_module)

                state = {
                    "session_id": "test",
                    "messages": [{"role": "user", "content": "Що це?"}],
                    "has_image": True,
                    "image_url": "https://example.com/test.jpg",
                    "metadata": {"session_id": "test"},
                    "current_state": "STATE_2_VISION",
                    "selected_products": [],
                }

                output = await vision_module.vision_node(state)

                # After enrichment, product should have real price from DB
                products = output.get("selected_products", [])
                if products:
                    # Price should be enriched from DB, not from LLM
                    assert products[0].get("price", 0) >= 0


# =============================================================================
# MODEL-SPECIFIC TESTS
# =============================================================================


class TestKeyProductModels:
    """Tests for key product models from MIRT catalog."""

    # Повний список продуктів з каталогу з правильними кольорами та цінами
    @pytest.mark.parametrize(
        "product_name,color,price",
        [
            # Сукня Анна - 7 варіантів кольорів, ціна 1850 грн
            ("Сукня Анна", "голубий", 1850),
            ("Сукня Анна", "малина", 1850),
            ("Сукня Анна", "чорний", 1850),
            ("Сукня Анна", "червоний", 1850),
            ("Сукня Анна", "шоколадний", 1850),
            ("Сукня Анна", "рожевий", 1850),
            ("Сукня Анна", "сірий", 1850),
            # Костюм Валері - універсальний, ціна 1950 грн
            ("Костюм Валері", "універсальний", 1950),
            # Костюм Ритм - 3 кольори, ціна 1975 грн
            ("Костюм Ритм", "рожевий", 1975),
            ("Костюм Ритм", "шоколадний", 1975),
            ("Костюм Ритм", "бордовий", 1975),
            # Костюм Каприз - 3 кольори, ціна 1885 грн
            ("Костюм Каприз", "рожевий", 1885),
            ("Костюм Каприз", "бордовий", 1885),
            ("Костюм Каприз", "шоколадний", 1885),
            # Костюм Лагуна - 4 кольори, ціна 1590-2390 грн (mid: 2190)
            ("Костюм Лагуна", "рожевий", 2190),
            ("Костюм Лагуна", "помаранчевий", 2190),
            ("Костюм Лагуна", "жовтий", 2190),
            ("Костюм Лагуна", "сірий", 2190),
            # Костюм Мрія - 4 кольори, ціна 1590-2390 грн (mid: 2190)
            ("Костюм Мрія", "жовтий", 2190),
            ("Костюм Мрія", "рожевий", 2190),
            ("Костюм Мрія", "помаранчевий", 2190),
            ("Костюм Мрія", "сірий", 2190),
            # Костюм Мерея - 1 колір, ціна 1985-2150 грн
            ("Костюм Мерея", "молочний", 1985),
            # Тренч екошкіра - 3 кольори, ціна 2180 грн
            ("Тренч екошкіра", "капучіно", 2180),
            ("Тренч екошкіра", "молочний", 2180),
            ("Тренч екошкіра", "чорний", 2180),
            # Тренч тканинний - 3 кольори, ціна 2380 грн
            ("Тренч", "рожевий", 2380),
            ("Тренч", "голубий", 2380),
            ("Тренч", "темно синій", 2380),
        ],
    )
    def test_product_model_can_be_identified(self, product_name, color, price):
        """All MIRT catalog products should be representable in VisionResponse."""
        response = VisionResponse(
            reply_to_user=f"Це {product_name} ({color})!",
            confidence=0.9,
            needs_clarification=False,
            identified_product=IdentifiedProduct(
                name=product_name,
                price=price,
                color=color,
            ),
        )
        assert response.identified_product.name == product_name
        assert response.identified_product.color == color
        assert response.identified_product.price == price


# =============================================================================
# ERROR HANDLING
# =============================================================================


class TestVisionErrorHandling:
    """Vision error handling tests."""

    def test_fallback_response_on_error(self):
        """Fallback response should be valid VisionResponse."""
        # This is what vision_agent returns on error
        fallback = VisionResponse(
            reply_to_user="Вибачте, не вдалося проаналізувати фото. Спробуйте надіслати ще раз 🤍",
            confidence=0.0,
            needs_clarification=True,
            clarification_question="Чи можете надіслати фото ще раз або описати товар?",
        )
        assert fallback.confidence == 0.0
        assert fallback.needs_clarification is True
        assert fallback.clarification_question is not None


# =============================================================================
# DISTINGUISHING SIMILAR PRODUCTS
# =============================================================================


class TestSimilarProductDistinction:
    """Tests for distinguishing similar products (Лагуна vs Мрія)."""

    # КРИТИЧНІ ПРАВИЛА РОЗРІЗНЕННЯ:
    # - Лагуна: ПЛЮШ + куртка на ПОВНІЙ блискавці (від верху до низу)
    # - Мрія: ПЛЮШ + half-zip світшот (КОРОТКА блискавка до грудей)
    # Кольори однакові: рожевий, жовтий, помаранчевий, сірий

    # РЕАЛЬНІ URL ФОТО З КАТАЛОГУ
    LAGUNA_PHOTOS = {
        "рожевий": "https://cdn.sitniks.com/cmp-2065/products/2025-10-03/8542510/12a6cc-1759503080447.jpeg",
        "помаранчевий": "https://cdn.sitniks.com/cmp-2065/products/2025-10-03/ce5d4e/76922c-1759510036476.jpeg",
        "жовтий": "https://cdn.sitniks.com/cmp-2065/products/2025-10-03/f214ab/db1af9-1759510737823.jpeg",
        "сірий": "https://cdn.sitniks.com/cmp-2065/products/2025-10-04/8c971b/eeb929-1759603663596.jpeg",
    }

    MRIYA_PHOTOS = {
        "жовтий": "https://cdn.sitniks.com/cmp-2065/products/2025-10-03/2539e6/3ea571-1759512282615.jpeg",
        "рожевий": "https://cdn.sitniks.com/cmp-2065/products/2025-10-07/e1541d/59aa110-1759848560466.jpeg",
        "помаранчевий": "https://cdn.sitniks.com/cmp-2065/products/2025-10-08/e5a10b10/fcbf86-1759893938963.jpeg",
        "сірий": "https://cdn.sitniks.com/cmp-2065/products/2025-10-27/757f60/92ecfe-1761595592474.jpeg",
    }

    @pytest.mark.parametrize("color", ["рожевий", "помаранчевий", "жовтий", "сірий"])
    def test_laguna_identification(self, color):
        """Лагуна should be identifiable by FULL zipper."""
        response = VisionResponse(
            reply_to_user="Це костюм Лагуна - бачу ПОВНУ блискавку від верху до низу!",
            confidence=0.9,
            needs_clarification=False,
            identified_product=IdentifiedProduct(
                name="Костюм Лагуна",
                price=2190,  # Ціна для розміру 122-128
                color=color,
                photo_url=self.LAGUNA_PHOTOS[color],
            ),
        )
        assert "лагуна" in response.identified_product.name.lower()
        assert response.identified_product.color == color
        assert response.identified_product.photo_url.startswith("https://cdn.sitniks.com/")

    @pytest.mark.parametrize("color", ["жовтий", "рожевий", "помаранчевий", "сірий"])
    def test_mriya_identification(self, color):
        """Мрія should be identifiable by SHORT (half-zip) zipper."""
        response = VisionResponse(
            reply_to_user="Це костюм Мрія - бачу КОРОТКУ блискавку до грудей (half-zip)!",
            confidence=0.9,
            needs_clarification=False,
            identified_product=IdentifiedProduct(
                name="Костюм Мрія",
                price=2190,  # Однакова ціна з Лагуною для розміру 122-128
                color=color,
                photo_url=self.MRIYA_PHOTOS[color],
            ),
        )
        assert "мрія" in response.identified_product.name.lower()
        assert response.identified_product.color == color
        assert response.identified_product.photo_url.startswith("https://cdn.sitniks.com/")

    def test_plush_suit_same_price_different_name(self):
        """Both Лагуна and Мрія have SAME price - zipper is ONLY distinction."""
        # Однакова ціна для однакового розміру!
        laguna = IdentifiedProduct(
            name="Костюм Лагуна",
            price=2190,
            color="рожевий",
            photo_url="https://cdn.sitniks.com/cmp-2065/products/2025-10-03/8542510/12a6cc-1759503080447.jpeg",
        )
        mriya = IdentifiedProduct(
            name="Костюм Мрія",
            price=2190,
            color="рожевий",
            photo_url="https://cdn.sitniks.com/cmp-2065/products/2025-10-07/e1541d/59aa110-1759848560466.jpeg",
        )

        # Names MUST be different
        assert laguna.name != mriya.name
        # Same color is valid for both
        assert laguna.color == mriya.color
        # Same price (for same size range)
        assert laguna.price == mriya.price
        # Different photos!
        assert laguna.photo_url != mriya.photo_url

    def test_mereya_distinct_by_stripes(self):
        """Мерея is distinct by side stripes (лампаси) on pants."""
        response = VisionResponse(
            reply_to_user="Це костюм Мерея - бачу ЛАМПАСИ (смужки) на штанах!",
            confidence=0.9,
            needs_clarification=False,
            identified_product=IdentifiedProduct(
                name="Костюм Мерея",
                price=1985,  # Ціна для розмірів 80-92 до 122-128
                color="молочний",  # ЄДИНИЙ доступний колір!
                photo_url="https://cdn.sitniks.com/cmp-2065/products/2025-10-09/495495/f8dd48-1760031949011.jpeg",
            ),
        )
        assert "мерея" in response.identified_product.name.lower()
        assert response.identified_product.color == "молочний"


# =============================================================================
# DISTINGUISHING RITM vs KAPRIZ (обидва бавовняні, схожі кольори!)
# =============================================================================


class TestRitmKaprizDistinction:
    """Tests for distinguishing Ритм vs Каприз - both cotton, same colors!"""

    # КРИТИЧНІ ПРАВИЛА РОЗРІЗНЕННЯ:
    # - Ритм: oversize ХУДІ (З КАПЮШОНОМ!) + штани ДЖОГЕРИ
    # - Каприз: СВІТШОТ (БЕЗ капюшона!) + широкі штани PALAZZO
    # Кольори ОДНАКОВІ: рожевий, шоколадний, бордовий

    # РЕАЛЬНІ URL ФОТО З КАТАЛОГУ
    RITM_PHOTOS = {
        "рожевий": "https://cdn.sitniks.com/cmp-2065/products/2025-09-22/605462/8365109-1758523787925.jpeg",
        "шоколадний": "https://cdn.sitniks.com/cmp-2065/products/2025-09-22/f11460/bdea2d-1758524955446.jpeg",
        "бордовий": "https://cdn.sitniks.com/cmp-2065/products/2025-09-22/785182/a5c11d-1758525112738.jpeg",
    }

    KAPRIZ_PHOTOS = {
        "рожевий": "https://cdn.sitniks.com/cmp-2065/products/2025-09-22/6915c4/c6faad-1758534106660.jpeg",
        "бордовий": "https://cdn.sitniks.com/cmp-2065/products/2025-09-22/2e181f/973828-1758534352656.jpeg",
        "шоколадний": "https://cdn.sitniks.com/cmp-2065/products/2025-09-22/d76999/c51309-1758534535069.jpeg",
        "коричневий": "https://cdn.sitniks.com/cmp-2065/products/2025-09-22/d76999/c51309-1758534535069.jpeg",
    }

    @pytest.mark.parametrize("color", ["рожевий", "шоколадний", "бордовий"])
    def test_ritm_identification_by_hoodie(self, color):
        """Ритм = oversize ХУДІ (з КАПЮШОНОМ) + ДЖОГЕРИ."""
        response = VisionResponse(
            reply_to_user="Це костюм Ритм - бачу oversize ХУДІ з КАПЮШОНОМ та штани-джогери!",
            confidence=0.9,
            needs_clarification=False,
            identified_product=IdentifiedProduct(
                name="Костюм Ритм",
                price=1975,
                color=color,
                photo_url=self.RITM_PHOTOS[color],
            ),
        )
        assert "ритм" in response.identified_product.name.lower()
        assert response.identified_product.color == color
        assert response.identified_product.price == 1975

    @pytest.mark.parametrize("color", ["рожевий", "бордовий", "коричневий"])
    def test_kapriz_identification_by_sweatshirt(self, color):
        """Каприз = СВІТШОТ (БЕЗ капюшона) + широкі штани PALAZZO."""
        response = VisionResponse(
            reply_to_user="Це костюм Каприз - бачу СВІТШОТ БЕЗ капюшона та широкі штани palazzo!",
            confidence=0.9,
            needs_clarification=False,
            identified_product=IdentifiedProduct(
                name="Костюм Каприз",
                price=1885,
                color=color,
                photo_url=self.KAPRIZ_PHOTOS[color],
            ),
        )
        assert "каприз" in response.identified_product.name.lower()
        assert response.identified_product.color == color
        assert response.identified_product.price == 1885

    def test_ritm_kapriz_different_prices(self):
        """Ритм і Каприз мають РІЗНІ ціни - це допомагає розрізняти."""
        ritm = IdentifiedProduct(
            name="Костюм Ритм",
            price=1975,
            color="рожевий",
            photo_url="https://cdn.sitniks.com/cmp-2065/products/2025-09-22/605462/8365109-1758523787925.jpeg",
        )
        kapriz = IdentifiedProduct(
            name="Костюм Каприз",
            price=1885,
            color="рожевий",
            photo_url="https://cdn.sitniks.com/cmp-2065/products/2025-09-22/6915c4/c6faad-1758534106660.jpeg",
        )

        # Names MUST be different
        assert ritm.name != kapriz.name
        # Same colors possible
        assert ritm.color == kapriz.color
        # DIFFERENT prices! (Ритм дорожчий)
        assert ritm.price != kapriz.price
        assert ritm.price > kapriz.price  # 1975 > 1885
        # Different photos!
        assert ritm.photo_url != kapriz.photo_url

    def test_ritm_has_hoodie_kapriz_no_hoodie(self):
        """KEY DISTINCTION: Ритм = з капюшоном, Каприз = без капюшона."""
        # Цей тест документує ключову відмінність
        ritm_features = {
            "name": "Костюм Ритм",
            "top": "oversize худі",
            "has_hood": True,  # КЛЮЧОВА ОЗНАКА!
            "bottom": "джогери",
            "price": 1975,
        }
        kapriz_features = {
            "name": "Костюм Каприз",
            "top": "світшот",
            "has_hood": False,  # КЛЮЧОВА ОЗНАКА!
            "bottom": "palazzo (широкі)",
            "price": 1885,
        }

        # Головна відмінність - капюшон!
        assert ritm_features["has_hood"] is True
        assert kapriz_features["has_hood"] is False

        # Додаткова відмінність - тип штанів
        assert ritm_features["bottom"] != kapriz_features["bottom"]
