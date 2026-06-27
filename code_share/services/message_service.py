try:
    from code_share.core.services.message_service import *  # noqa: F401,F403
except ImportError:
    from core.services.message_service import *  # noqa: F401,F403
