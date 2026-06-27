"""
挑战 3 - 包结构兼容测试
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from code_share.core.services.social_runtime import SocialRuntime
from code_share.core.utils.protocol import Protocol
from code_share.services.social_runtime import SocialRuntime as CompatSocialRuntime
from code_share.utils.protocol import Protocol as CompatProtocol


def test_core_package_is_primary_and_legacy_imports_still_work():
    assert SocialRuntime is CompatSocialRuntime
    assert Protocol is CompatProtocol
    assert Protocol.DEFAULT_TCP_PORT == 7779
