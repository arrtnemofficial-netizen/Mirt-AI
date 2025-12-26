import importlib
import warnings


def test_memory_service_shim_exports():
    module = importlib.import_module("src.services.memory_service")
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always", DeprecationWarning)
        importlib.reload(module)

    assert any(
        isinstance(item.message, DeprecationWarning) for item in captured
    ), "Expected DeprecationWarning on reload"
    assert hasattr(module, "MemoryService")
    assert hasattr(module, "create_memory_service")
    assert hasattr(module, "MIN_IMPORTANCE_TO_STORE")
    assert hasattr(module, "MIN_SURPRISE_TO_STORE")
    assert hasattr(module, "DEFAULT_FACTS_LIMIT")
    assert hasattr(module, "MAX_FACTS_LIMIT")
