from enum import Enum


class SystemKeys(str, Enum):
    TEXTS = "system.texts"
    CRM_CONFIG = "system.crm_config"
    STREAMING = "system.streaming"
    CRM_ERROR = "system.crm_error"
    MANYCHAT = "system.manychat"
    BASE_IDENTITY = "system.base_identity"
    SNIPPETS = "system.snippets"
    MAIN_AGENT = "system.main_agent"
    PAYMENT_CONTEXT = "system.payment_context"
    MEMORY_PARSER = "system.memory_parser"
    MODERATION = "system.moderation"
    STATE_MACHINE = "system.state_machine"
    CLIENT_PARSER = "system.client_parser"
    VISION = "system.vision"
    AUTOMATION = "system.automation"
    INTENTS = "system.intents"
    SYSTEM_MESSAGES = "system.system_messages"
    FALLBACKS = "system.fallbacks"


class DomainKeys(str, Enum):
    MAIN_MAIN = "main.main"
    PAYMENT_MAIN = "payment.main"
    MEMORY_MAIN = "memory.main"
    VISION_MAIN = "vision.main"
