"""UDP discovery packet dispatch."""

import time

from core.backend.shared.helpers import Helpers
from core.backend.shared.protocol import Protocol


class UDPPacketRouter:
    """Turns parsed UDP packets into discovery state changes and callbacks."""

    def __init__(self, service):
        self.service = service

    def handle_datagram(self, data: bytes, addr) -> bool:
        packet = Protocol.parse_udp_packet(data)
        if not packet:
            return False

        sender_ip = addr[0]
        packet_type = packet.get("type")
        self.service._bump_diagnostic("receive_packets")
        self.service._mark_diagnostic(last_receive_at=time.time(), last_error="")

        local_ips = Helpers.get_local_ips()
        if self._is_self_packet(packet, sender_ip, addr, local_ips):
            return True

        record_ip = "127.0.0.1" if sender_ip in local_ips else sender_ip
        if packet_type == Protocol.UDP_PING:
            self._handle_ping(packet, addr, sender_ip, record_ip, local_ips)
        elif packet_type == Protocol.UDP_PONG:
            self._handle_pong(packet, record_ip)
        elif packet_type == Protocol.FRIEND_REQUEST:
            self._handle_friend_request(packet, record_ip)
        return True

    def _is_self_packet(self, packet: dict, sender_ip: str, addr, local_ips) -> bool:
        if sender_ip not in local_ips:
            return False
        packet_device_id = packet.get("device_id", "")
        service = self.service
        if packet_device_id and service.device_id and packet_device_id == service.device_id:
            return True
        return not packet_device_id and (
            addr[1] == service.port or packet.get("device_name") == service.device_name
        )

    def _handle_ping(self, packet: dict, addr, sender_ip: str, record_ip: str, local_ips):
        service = self.service
        service._bump_diagnostic("receive_ping")
        advertised_ip = "127.0.0.1" if sender_ip in local_ips else Helpers.get_default_ip()
        pong_data = Protocol.create_pong_packet(
            service.device_name,
            advertised_ip,
            service.tcp_port,
            service.user_id,
            service.device_id,
            service._get_candidate_ips(),
        )
        service.sock.sendto(pong_data, addr)
        self._remember_peer(packet, record_ip)

    def _handle_pong(self, packet: dict, record_ip: str):
        self.service._bump_diagnostic("receive_pong")
        candidate_ips = packet.get("candidate_ips", []) or []
        packet_ip = packet.get("ip", "")
        if packet_ip:
            candidate_ips = [packet_ip, *candidate_ips]
        self._remember_peer(packet, record_ip, candidate_ips)

    def _handle_friend_request(self, packet: dict, record_ip: str):
        service = self.service
        service._bump_diagnostic("receive_friend_request")
        if service.on_friend_request_packet:
            service.on_friend_request_packet(record_ip, packet)

    def _remember_peer(self, packet: dict, record_ip: str, candidate_ips=None):
        self.service._add_device(
            record_ip,
            packet.get("device_name", "Unknown"),
            packet.get("tcp_port", Protocol.DEFAULT_TCP_PORT),
            packet.get("user_id", ""),
            packet.get("device_id", ""),
            candidate_ips if candidate_ips is not None else packet.get("candidate_ips", []) or [],
        )
