"""
Verification script for Vision Node Refactoring.
"""
import asyncio
import sys
import unittest
from unittest.mock import MagicMock, AsyncMock, patch
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Add src to path
import os
sys.path.append(os.getcwd())

class TestVisionRefactor(unittest.IsolatedAsyncioTestCase):
    
    async def test_import_vision_node(self):
        """Test that vision_node can be imported from the new package."""
        logger.info("Testing import from src.agents.langgraph.nodes.vision")
        from src.agents.langgraph.nodes.vision import vision_node
        self.assertTrue(callable(vision_node))
        
        logger.info("Testing import from src.agents.langgraph.nodes (facade)")
        from src.agents.langgraph.nodes import vision_node as vn_facade
        self.assertTrue(callable(vn_facade))
        self.assertEqual(vision_node, vn_facade)

    @patch("src.agents.langgraph.nodes.vision.node.run_vision")
    @patch("src.agents.langgraph.nodes.vision.node.enrich_product_from_db")
    async def test_vision_node_execution(self, mock_enrich, mock_run_vision):
        """Test basic execution of vision_node."""
        logger.info("Testing vision_node execution flow")
        
        # Setup Mocks
        from src.agents.langgraph.nodes.vision import vision_node
        from src.agents.pydantic.models import VisionResponse, ProductMatch
        from src.core.state_machine import State

        # Mock Vision Response
        mock_response = VisionResponse(
            reply_to_user="Found it",
            identified_product=ProductMatch(name="Test Product", color="Red"),
            confidence=0.9,
            needs_clarification=False,
            alternative_products=[]
        )
        mock_run_vision.return_value = mock_response

        # Mock Enricher
        mock_enrich.return_value = {
            "id": 1,
            "name": "Test Product",
            "price": 1000,
            "price_display": "1000 грн",
            "photo_url": "http://example.com/photo.jpg",
            "_catalog_row": {},
            "_color_options": ["Red", "Blue"]
        }

        # Setup State
        state = {
            "messages": [{"role": "user", "content": "Check this photo"}],
            "image_url": "http://example.com/input.jpg",
            "metadata": {"session_id": "test_session"}
        }

        # Run Node
        result = await vision_node(state)

        # Assertions
        self.assertEqual(result["current_state"], State.STATE_2_VISION.value)
        self.assertEqual(result["dialog_phase"], "VISION_DONE")
        self.assertTrue(result["has_image"])
        self.assertEqual(len(result["selected_products"]), 1)
        self.assertEqual(result["selected_products"][0]["name"], "Test Product")
        
        # Check messages
        messages = result["messages"]
        self.assertTrue(len(messages) > 0)
        # Identify key parts of response
        content_str = str(messages)
        self.assertIn("Test Product", content_str)
        self.assertIn("Red", content_str) 

        logger.info("Vision node execution verification passed!")

if __name__ == "__main__":
    unittest.main()
