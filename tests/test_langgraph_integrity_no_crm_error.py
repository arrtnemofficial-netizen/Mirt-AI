def test_langgraph_does_not_reference_crm_error_node():
    # We removed crm_error node completely; ensure no lingering references
    from src.agents.langgraph import edges, graph

    # Routing literals / route mapping should not include crm_error
    assert "crm_error" not in str(edges.__dict__)
    assert "crm_error" not in str(graph.__dict__)


