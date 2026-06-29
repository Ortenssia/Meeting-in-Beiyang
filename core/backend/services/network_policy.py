"""Shared network tuning policy for the P2P service layer."""

from dataclasses import dataclass


@dataclass(frozen=True)
class NetworkPolicy:
    """Runtime knobs for discovery, TCP connections, messaging and files."""

    profile_name: str = "campus_lan"

    tcp_connect_timeout: float = 6.0
    tcp_heartbeat_interval: float = 30.0
    ip_monitor_interval: float = 15.0

    udp_broadcast_interval: float = 4.0
    udp_active_scan_interval: float = 20.0
    udp_target_cache_ttl: float = 12.0

    message_heartbeat_interval: float = 15.0
    file_chunk_size: int = 256 * 1024
    file_ack_interval: int = 32
    file_ack_timeout: float = 45.0
    file_max_attempts: int = 5
    file_progress_min_interval: float = 0.125
    file_progress_pct_step: int = 5


CAMPUS_NETWORK_POLICY = NetworkPolicy()
DEFAULT_NETWORK_POLICY = CAMPUS_NETWORK_POLICY
