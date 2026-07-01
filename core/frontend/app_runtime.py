"""Runtime setup and callback binding for BeiyangApp."""

from core.backend.services.social_runtime import RuntimeConfig, SocialRuntime


class AppRuntimeCoordinator:
    """Own SocialRuntime construction and callback wiring for the UI app."""

    def __init__(self, app):
        self.app = app

    def init_services(self):
        app = self.app
        app.runtime = SocialRuntime(
            RuntimeConfig(
                tcp_port=app.tcp_port,
                udp_port=app.udp_port,
                db_path=app.db_path,
                name_override=app.name_override,
                avatar_dir=str(app.paths.received_avatars_dir),
                paths=app.paths,
            )
        ).initialize()
        app.friend_db = app.runtime.friend_db
        app.connection_manager = app.runtime.connection_manager
        app.udp_service = app.runtime.udp_service
        app.message_service = app.runtime.message_service
        app.social_service = app.runtime.social_service
        app.device_name = app.runtime.device_name

    def bind_callbacks(self):
        app = self.app
        app.runtime.on_discovery_changed = lambda: app._safe(app._on_discovery)
        app.runtime.on_online_changed = lambda: app._safe(app._on_online)
        app.runtime.on_friends_changed = lambda: app._safe(app._on_friends)
        app.runtime.on_message_received = lambda n, c, t, mid="": app._safe(
            lambda: app._on_message(n, c, t, mid)
        )
        app.runtime.on_friend_request = lambda p, m, ip=None: app._safe(
            lambda: app._on_friend_request(p, m, ip)
        )
        app.runtime.on_friend_accepted = lambda n, ip: app._safe(app._on_online)
        app.runtime.on_friend_deleted = lambda n: app._safe(lambda: app._on_friend_deleted(n))
        app.runtime.on_error = lambda msg: print(f"[BeiyangSocial] error: {msg}")
        app.runtime.on_group_message_received = lambda gid, s, c, ts: app._safe(
            lambda: app._on_group_message(gid, s, c, ts)
        )
        app.runtime.on_moments_changed = lambda: app._safe(app._on_moments_changed)
        app.runtime.on_notifications_changed = lambda: app._safe(app._on_notifications_changed)

        app.message_service.on_friend_profile_update_available = (
            lambda name: app._safe(lambda: app._on_profile_update_available(name))
        )
        app.message_service.on_friend_profile_updated = (
            lambda name: app._safe(lambda: app._on_profile_updated(name))
        )
        app.message_service.on_file_received = (
            lambda name, path, ts: app._safe(lambda: app._on_file_received(name, path, ts))
        )
        app.message_service.on_file_progress = (
            lambda fid, peer, name, done, total, sending, confirmed=0: app._safe(
                lambda: app.views["chat"].on_file_progress(
                    fid,
                    peer,
                    name,
                    done,
                    total,
                    sending,
                    confirmed=confirmed,
                )
            )
        )
        app.message_service.on_file_offer_received = (
            lambda name, filename, size, fid: app._safe(
                lambda: app._on_file_offer_received(name, filename, size, fid)
            )
        )
        app.message_service.on_file_status_changed = (
            lambda fid, status: app._safe(
                lambda: app.views["chat"].on_file_status_changed(fid, status)
            )
        )
