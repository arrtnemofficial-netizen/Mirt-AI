"""
Verification script for Agent Refactoring (Phase 4).
Tests:
1. Tools: Regex extraction, Product merging.
2. Logic: Phase determination, upsell check.
3. Node: Integration flow (mocked).
"""
import asyncio
import sys
import unittest
from unittest.mock import MagicMock, AsyncMock, patch
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

import os
sys.path.append(os.getcwd())

from src.agents.langgraph.nodes.agent import tools, logic, catalog, agent_node
from src.core.state_machine import State

class TestAgentRefactor(unittest.IsolatedAsyncioTestCase):

    def test_tools_regex(self):
        """Test size and height extraction tools."""
        logger.info("Testing tools.extract_size_from_response")
        
        # Test Cyrillic
        msg = MagicMock()
        msg.content = "Я раджу вам розмір 146-152."
        self.assertEqual(tools.extract_size_from_response([msg]), "146-152")
        
        # Test Latin
        msg.content = "Video suggests size 122-128" # No pattern match for English yet?
        # Actually patterns are: rozmir/radzhu/pidide
        msg.content = "pidide 122-128"
        self.assertEqual(tools.extract_size_from_response([msg]), "122-128")

    def test_tools_merge(self):
        """Test product merging logic."""
        logger.info("Testing tools.merge_products")
        existing = [{"id": 1, "name": "A", "price": 0}]
        incoming = [{"id": 1, "name": "A", "price": 100}]
        
        merged = tools.merge_products(existing, incoming, append=False)
        self.assertEqual(merged[0]["price"], 100)
        self.assertEqual(len(merged), 1)

    def test_logic_upsell(self):
        """Test upsell trigger logic."""
        logger.info("Testing logic.should_trigger_upsell")
        
        # State-based trigger
        self.assertTrue(
            logic.should_trigger_upsell(
                [{"id": 1}],
                current_state="STATE_6_UPSELL",
                next_state="STATE_6_UPSELL",
                upsell_flow_active=False,
            )
        )

        # Flag trigger
        self.assertTrue(
            logic.should_trigger_upsell(
                [{"id": 1}],
                current_state="STATE_4_OFFER",
                next_state="STATE_4_OFFER",
                upsell_flow_active=True,
            )
        )

        # No trigger
        self.assertFalse(
            logic.should_trigger_upsell(
                [{"id": 1}],
                current_state="STATE_4_OFFER",
                next_state="STATE_4_OFFER",
                upsell_flow_active=False,
            )
        )

    @patch("src.agents.langgraph.nodes.agent.node.run_support")
    async def test_agent_node_flow(self, mock_run):
        """Test main agent node execution."""
        logger.info("Testing agent_node execution")
        
        from src.agents.pydantic.models import SupportResponse, ResponseMetadata, MessageItem
        
        # Mock Response
        mock_run.return_value = SupportResponse(
            event="simple_answer",
            messages=[MessageItem(content="Ціна 1500 грн")],
            metadata=ResponseMetadata(
                current_state=State.STATE_1_DISCOVERY.value,
                intent="DISCOVERY_OR_QUESTION"
            ),
            products=[]
        )
        
        state = {
            "messages": [{"role": "user", "content": "Скільки коштує?"}],
            "current_state": State.STATE_1_DISCOVERY.value,
            "dialog_phase": "INIT"
        }
        
        result = await agent_node(state)
        
        self.assertEqual(result["current_state"], State.STATE_1_DISCOVERY.value)
        self.assertEqual(result["detected_intent"], "DISCOVERY_OR_QUESTION")
        self.assertIn("Ціна 1500 грн", str(result["messages"]))
        
        logger.info("Agent node verification passed!")

if __name__ == "__main__":
    unittest.main()
