try:
    from code_share.core.services.social_service import *  # noqa: F401,F403
except ImportError:
    from core.services.social_service import *  # noqa: F401,F403
