"""CRM integrations package."""
from src.integrations.crm.base import BaseCRMClient, CRMResponse
from src.integrations.crm.snitkix import SnitkixCRMClient

__all__ = ["BaseCRMClient", "CRMResponse", "SnitkixCRMClient"]
