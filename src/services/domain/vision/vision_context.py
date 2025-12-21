"""
Vision Context Service.
=======================
Responsible for assembling the rich context for Vision Agent.
Decouples prompt engineering from agent logic.
Optimized with TTL caching to reduce I/O and DB load.
"""
import logging
import time
from typing import Any, Dict, Optional
import json
from pathlib import Path
import yaml

from src.services.data.catalog_service import CatalogService

logger = logging.getLogger(__name__)

class VisionContextService:
    """Service to build structured context for Vision Agent with TTL Caching."""

    # Cache settings (seconds)
    DEFAULT_TTL = 600  # 10 minutes

    def __init__(self, catalog: CatalogService | None = None):
        self.catalog = catalog or CatalogService()
        self._cache: Dict[str, Any] = {}
        self._cache_timestamps: Dict[str, float] = {}

    def invalidate_cache(self, part: Optional[str] = None):
        """Clear the cache. If part is specified, only clears that part."""
        if part:
            self._cache.pop(part, None)
            self._cache_timestamps.pop(part, None)
            logger.info("Invalidated vision context cache part: %s", part)
        else:
            self._cache.clear()
            self._cache_timestamps.clear()
            logger.info("Invalidated entire vision context cache")

    def _get_from_cache(self, key: str) -> Optional[Any]:
        """Get item from cache if it exists and hasn't expired."""
        if key in self._cache:
            timestamp = self._cache_timestamps.get(key, 0)
            if time.time() - timestamp < self.DEFAULT_TTL:
                return self._cache[key]
            else:
                # Expired
                self.invalidate_cache(key)
        return None

    def _save_to_cache(self, key: str, value: Any):
        """Save item to cache with current timestamp."""
        self._cache[key] = value
        self._cache_timestamps[key] = time.time()

    async def get_reference_image_urls(self, product_names: list[str], max_per_product: int = 2) -> list[str]:
        """Get reference image URLs for products (Legacy compat)."""
        ref_map = self._load_reference_images_map()
        urls = []
        for name in product_names:
             product_urls = ref_map.get(name) or []
             for url in product_urls[:max_per_product]:
                 if url not in urls:
                     urls.append(url)
        return urls
        
    def get_reference_images_map(self, product_names: list[str]) -> dict[str, list[str]]:
         ref_map = self._load_reference_images_map()
         result = {}
         for name in product_names:
             if name in ref_map:
                 result[name] = ref_map[name]
         return result

    def _load_reference_images_map(self) -> dict[str, list[str]]:
        # This is a small JSON, but we can still cache it if needed
        cache_key = "reference_images_map"
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            return cached

        test_set_path = self._get_data_path() / "test_set.json"
        try:
            with open(test_set_path, encoding="utf-8") as f:
                test_set = json.load(f)
            
            ref_map: dict[str, list[str]] = {}
            if not isinstance(test_set, list): return {}

            for item in test_set:
                if not isinstance(item, dict): continue
                name = item.get("expected_product")
                url = item.get("image_url")
                if not isinstance(name, str) or not isinstance(url, str): continue
                if not url.startswith("https://"): continue
                
                ref_map.setdefault(name, [])
                if url not in ref_map[name]:
                    ref_map[name].append(url)
            
            self._save_to_cache(cache_key, ref_map)
            return ref_map
        except Exception:
            return {}
            
    async def get_full_context(self) -> str:
        """Get complete vision context block (Cached)."""
        cache_key = "full_context"
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            return cached

        parts = []
        
        # 1. Live Catalog Guide
        vision_guide = await self._load_vision_guide_from_db()
        if vision_guide:
            parts.append(f"\n---\n{vision_guide}")
            
        # 2. Recognition Tips (Deep Rules)
        recognition_tips = self._load_recognition_tips_from_json()
        if recognition_tips:
            parts.append(f"\n---\n{recognition_tips}")

        # 3. Model Rules (Static DB)
        model_rules = self.get_model_rules_text()
        if model_rules:
            parts.append(f"\n---\n{model_rules}")
            
        full_context = "\n".join(parts)
        self._save_to_cache(cache_key, full_context)
        return full_context

    async def _load_vision_guide_from_db(self) -> str:
        """Load prompt-ready guide from Catalog Service (Cached)."""
        cache_key = "vision_guide"
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            return cached

        try:
            products = await self.catalog.get_products_for_vision()

            if not products:
                logger.warning("No products from DB, falling back to JSON")
                res = self._load_vision_guide_from_json()
                self._save_to_cache(cache_key, res)
                return res

            lines = [self._get_snippet("VISION_GUIDE_HEADER")[0] + "\n"]

            for product in products:
                lines.extend(self._format_product_entry(product))

            lines.append(self._build_detection_rules(products))
            res = "\n".join(lines)
            self._save_to_cache(cache_key, res)
            return res

        except Exception as e:
            logger.warning("Failed to load from DB: %s, falling back to JSON", e)
            res = self._load_vision_guide_from_json()
            self._save_to_cache(cache_key, res)
            return res

    def _format_product_entry(self, product: dict[str, Any]) -> list[str]:
        """Format single product for prompt using Registry templates."""
        try:
            template = self._get_snippet("VISION_PRODUCT_TEMPLATE")
            if not template:
                return []
            template_str = template[0]
            
            labels_json = self._get_snippet("VISION_LABELS")
            labels = json.loads(labels_json[0]) if labels_json else {}
            
            name = product.get("name", "Unknown")
            sku = product.get("sku") or product.get("id", "N/A")
            color = product.get("colors") or product.get("color", "")
            
            price_block = ""
            price_by_size = product.get("price_by_size")
            if price_by_size and isinstance(price_by_size, dict):
                prices = list(price_by_size.values())
                if prices:
                    min_p, max_p = min(prices), max(prices)
                    size_prices = ", ".join([f"{sz}: {int(pr)} {labels.get('currency_uah', 'грн')}" for sz, pr in price_by_size.items()])
                    
                    price_tmpl = self._get_snippet("VISION_PRICE_TEMPLATE")
                    if price_tmpl:
                        price_block = price_tmpl[0].format(
                            label_price=labels.get("price", "Price"),
                            min_price=int(min_p),
                            max_price=int(max_p),
                            label_depends=labels.get("depends", ""),
                            label_sizes=labels.get("sizes", "Sizes"),
                            size_prices=size_prices
                        )
            else:
                price = product.get("price")
                if price:
                    price_tmpl = self._get_snippet("VISION_PRICE_SINGLE_TEMPLATE")
                    if price_tmpl:
                        price_block = price_tmpl[0].format(
                            label_price=labels.get("price", "Price"),
                            price=price
                        )

            formatted = template_str.format(
                name=name,
                sku=sku,
                label_color=labels.get("color", "Color"), 
                color=color,
                label_fabric=labels.get("fabric", "Fabric"),
                fabric=product.get("fabric_type", ""),
                label_closure=labels.get("closure", "Closure"),
                closure=product.get("closure_type", ""),
                label_hood=labels.get("hood", "Hood"),
                hood=labels.get("yes") if product.get("has_hood") else (labels.get("no") if product.get("has_hood") is False else ""),
                label_pants=labels.get("pants", "Pants"),
                pants=product.get("pants_style", ""),
                label_back=labels.get("back", "Back"),
                back_view=product.get("back_view_description", ""),
                label_tips=labels.get("tips", "Tips"),
                tips="\n".join([f"  - {t}" for t in product.get("recognition_tips", [])[:3]]),
                label_confused=labels.get("confused", "Confused with"),
                confused_with=", ".join(product.get("confused_with", [])),
                label_description=labels.get("description", "Desc"),
                description=product.get("description", ""),
                price_block=price_block
            )
            
            # Clean up empty lines
            lines = [line for line in formatted.split("\n") if line.strip().endswith(":") is False]
            return lines

        except Exception as e:
            logger.error(f"Error formatting product entry: {e}")
            return []

    def _build_detection_rules(self, products: list[dict]) -> str:
        """Build global detection rules from product set."""
        by_fabric: dict[str, list[str]] = {}
        by_closure: dict[str, list[str]] = {}
        by_hood: dict[str, list[str]] = {"з капюшоном": [], "без капюшона": []}

        for p in products:
            name = p.get("name", "Unknown")
            base_name = name.split("(")[0].strip() if "(" in name else name

            fabric = p.get("fabric_type")
            if fabric:
                by_fabric.setdefault(fabric, []).append(base_name)

            closure = p.get("closure_type")
            if closure:
                by_closure.setdefault(closure, []).append(base_name)

            if p.get("has_hood"):
                by_hood["з капюшоном"].append(base_name)
            elif p.get("has_hood") is False:
                by_hood["без капюшона"].append(base_name)

        lines = ["\n" + self._get_snippet("VISION_DETECTION_RULES_HEADER")[0]]

        labels_json = self._get_snippet("VISION_LABELS")
        labels = json.loads(labels_json[0]) if labels_json else {}
        
        if by_fabric:
            lines.append(f"## {labels.get('det_fabric', 'By Fabric')}:")
            for fabric, names in by_fabric.items():
                unique = list(set(names))[:5]
                lines.append(f"- {fabric}: {', '.join(unique)}")

        if by_closure:
            lines.append(f"## {labels.get('det_closure', 'By Closure')}:")
            for closure, names in by_closure.items():
                unique = list(set(names))[:5]
                lines.append(f"- {closure}: {', '.join(unique)}")

        if by_hood["з капюшоном"] or by_hood["без капюшона"]:
            lines.append(f"## {labels.get('det_hood', 'By Hood')}:")
            if by_hood["з капюшоном"]:
                unique = list(set(by_hood["з капюшоном"]))[:5]
                lines.append(f"- {labels.get('hood_yes', 'With Hood')}: {', '.join(unique)}")
            if by_hood["без капюшона"]:
                unique = list(set(by_hood["без капюшона"]))[:5]
                lines.append(f"- {labels.get('hood_no', 'No Hood')}: {', '.join(unique)}")

        return "\n".join(lines)

    def _load_vision_guide_from_json(self) -> str:
        """Fallback JSON loader."""
        guide_path = self._get_data_path() / "vision_guide.json"
        try:
            with open(guide_path, encoding="utf-8") as f:
                guide = json.load(f)

            products = guide.get("visual_recognition_guide", {}).get("products", {})
            lines = [self._get_snippet("VISION_GUIDE_JSON_HEADER")[0] + "\n"]

            for sku, data in products.items():
                name = data.get("name", "Unknown")
                tips = data.get("recognition_tips", [])

                lines.append(f"## {name} (SKU: {sku})")
                for tip in tips[:3]:
                    lines.append(f"  - {tip}")
                lines.append("")

            return "\n".join(lines)
        except Exception as e:
            logger.warning("Failed to load vision_guide.json: %s", e)
            return ""

    def _load_recognition_tips_from_json(self) -> str:
        """Detailed recognition tips loader (Cached)."""
        cache_key = "recognition_tips"
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            return cached

        guide_path = self._get_data_path() / "vision_guide.json"
        
        try:
            with open(guide_path, encoding="utf-8") as f:
                guide = json.load(f)

            data = guide.get("visual_recognition_guide", {})
            products = data.get("products", {})
            detection_rules = data.get("detection_rules", {})

            lines = [self._get_snippet("VISION_GUIDE_FEATURES")[0] + "\n"]

            for _sku, product_data in products.items():
                self._append_product_tips(lines, product_data)

            labels_json = self._get_snippet("VISION_LABELS")
            labels = json.loads(labels_json[0]) if labels_json else {}

            lines.append(f"\n# {labels.get('det_rules_header', 'DETECTION RULES')}") 
            
            by_closure = detection_rules.get("by_closure", {})
            if by_closure:
                 lines.append(f"\n**{labels.get('det_closure', 'By Closure')}:**")
                 for closure_type, models in by_closure.items():
                     lines.append(f"- {closure_type}: {', '.join(models)}")

            by_texture = detection_rules.get("by_texture", {})
            if by_texture:
                lines.append(f"\n**{labels.get('det_texture', 'By Texture')}:**")
                for texture, models in by_texture.items():
                    lines.append(f"- {texture}: {', '.join(models)}")

            res = "\n".join(lines)
            self._save_to_cache(cache_key, res)
            return res

        except Exception as e:
            logger.warning("Failed to load recognition tips from JSON: %s", e)
            return ""

    def _append_product_tips(self, lines: list[str], product_data: dict[str, Any]):
        """Helper to append detailed tips for a product."""
        name = product_data.get("name", "Unknown")
        key_features = product_data.get("key_features", {})
        distinction = product_data.get("distinctive_features", {})
        recognition_by_angle = product_data.get("recognition_by_angle", {})

        labels_json = self._get_snippet("VISION_LABELS")
        labels = json.loads(labels_json[0]) if labels_json else {}

        lines.append(f"## {name}")

        fabric = key_features.get("fabric")
        if fabric:
            lines.append(f"- **{labels.get('fabric', 'Fabric')}**: {fabric}")
        
        markers = key_features.get("markers", [])
        if markers:
            lines.append(f"- **{labels.get('tips', 'Key Features')}**:")
            for marker in markers:
                lines.append(f"  - {marker}")

        if recognition_by_angle:
            front = recognition_by_angle.get("front")
            if front:
                lines.append(f"- **{labels.get('front', 'Front View')}**: {front}")
            detail = recognition_by_angle.get("detail")
            if detail:
                lines.append(f"- **{labels.get('detail', 'Detail')}**: {detail}")

        texture = product_data.get("texture_description")
        if texture:
             lines.append(f"- **{labels.get('texture', 'Texture')}**: {texture}")

        confused_with = distinction.get("confused_with", [])
        if confused_with:
            lines.append(f"- **⚠️ {labels.get('confused', 'Confused with')}**: {', '.join(confused_with)}")
            how = distinction.get("how_to_distinguish")
            if how:
                lines.append(f"- **{labels.get('how', 'How to distinguish')}**: {how.strip()}")
            critical = distinction.get("critical_check")
            if critical:
                 lines.append(f"- **🔍 {labels.get('critical', 'Critical check')}**: {critical.strip()}")

        unique = distinction.get("unique_identifier")
        if unique:
             lines.append(f"- **{labels.get('unique', 'Unique')}**: {unique}")

        lines.append("")

    def _get_data_path(self) -> Path:
        """Get path to data/vision/generated."""
        return Path(__file__).parent.parent.parent / "data" / "vision" / "generated"

    def get_model_names(self, max_models: int = 5) -> list[str]:
        """Get list of model names for Reference Images."""
        rules_path = self._get_data_path() / "model_rules.yaml"
        try:
             with open(rules_path, encoding="utf-8") as f:
                rules = yaml.safe_load(f)
             model_rules = rules.get("MODEL_RULES", {}) if isinstance(rules, dict) else {}
             if not isinstance(model_rules, dict):
                 return []
             return list(model_rules.keys())[:max_models]
        except Exception as e:
            logger.warning("Failed to load model names for reference: %s", e)
            return []

    def get_model_rules_text(self) -> str:
        """Load model rules DB text (Cached)."""
        cache_key = "model_rules"
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            return cached

        rules_path = self._get_data_path() / "model_rules.yaml"
        try:
             with open(rules_path, encoding="utf-8") as f:
                rules = yaml.safe_load(f)
             if not rules: return ""
             
             lines = []
             lines.append(self._get_snippet("VISION_MODEL_DB_HEADER")[0])

             model_rules = rules.get("MODEL_RULES", {})
             for name, data in model_rules.items():
                 lines.append(f"## {name}")
                 lines.append(f"- **{labels.get('category_label', 'Категорія')}**: {data.get('category', '?')}")
                 lines.append(f"- **{labels.get('fabric', 'Тканина')}**: {data.get('fabric_type', '?')}")
                 lines.append(f"- **{labels.get('price', 'Ціна')}**: {data.get('price', '?')} {labels.get('currency_uah', 'грн')}")

                 markers = data.get("visual_markers", [])
                 if markers:
                     lines.append(f"- **{labels.get('det_markers', 'Візуальні ознаки')}**:")
                     for m in markers:
                         lines.append(f"  - {m}")

                 identify = data.get("identify_by")
                 if identify:
                     lines.append(f"- **ГОЛОВНА ОЗНАКА**: {identify}")

                 confused = data.get("confused_with", [])
                 if confused:
                     lines.append(f"- **{labels.get('not_confuse_with', 'Не плутай з')}**: {', '.join(confused)}")
                     if data.get("how_to_distinguish"):
                         lines.append(f"- **{labels.get('how_distinguish', 'Як відрізнити')}**: {data['how_to_distinguish'].strip()}")
                     if data.get("critical_check"):
                         lines.append(f"- **⚠️ {labels.get('critical_check_upper', 'КРИТИЧНА ПЕРЕВІРКА')}**: {data['critical_check'].strip()}")

                 colors = data.get("colors", [])
                 if colors:
                     lines.append(f"- **Кольори**: {', '.join(colors)}")

                 lines.append("")
                 
             decision_tree = rules.get("DECISION_TREE", "")
             if decision_tree:
                 lines.append("# DECISION TREE")
                 lines.append(decision_tree)
                 
             res = "\n".join(lines)
             self._save_to_cache(cache_key, res)
             return res

        except Exception as e:
            logger.warning("Failed to load model rules: %s", e)
            return ""

    def _get_snippet(self, header: str) -> list[str]:
        from src.agents.langgraph.nodes.vision.snippets import get_snippet_by_header
        return get_snippet_by_header(header)
