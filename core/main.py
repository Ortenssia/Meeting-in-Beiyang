import os
import sys

if __package__ in (None, ""):
    core_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(core_dir)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)


import argparse
from core.config import get_app_paths
from core.ops.bootstrap import prepare_runtime
from core.ops.logging_config import configure_logging

def main():
    """Start the desktop or packaged Flet application."""
    prepare_runtime()

    parser = argparse.ArgumentParser(description="相识北洋社交应用")
    parser.add_argument("--port", type=int, default=7779, help="TCP Listening Port")
    parser.add_argument("--udp-port", type=int, default=8890, help="UDP Discovery Port")
    parser.add_argument("--db", type=str, default="friends.db", help="SQLite DB File")
    parser.add_argument("--name", type=str, default="", help="Username/Device name Override")
    parser.add_argument(
        "--instance",
        type=str,
        default="",
        help="Isolate writable data for a local test instance",
    )
    parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        default="INFO",
        help="Application log level",
    )
    args, _unknown = parser.parse_known_args()

    configure_logging(args.log_level)
    paths = get_app_paths()
    if args.instance:
        paths = paths.for_instance(args.instance)
        paths.ensure_writable_dirs()

    db_path = paths.resolve_db_path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    from core.frontend import BeiyangApp

    BeiyangApp(
        tcp_port=args.port,
        udp_port=args.udp_port,
        db_path=str(db_path),
        name_override=args.name,
        app_paths=paths,
    ).run()


if __name__ == "__main__":
    main()
