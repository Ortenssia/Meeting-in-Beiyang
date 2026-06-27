"""
Code Share - 相识北洋社交应用 (挑战3)
运行方式: python core/main.py
"""
import sys
import os

# 禁用 Kivy 自带的命令行参数解析，防止其拦截自定义的 --port 等参数
os.environ["KIVY_NO_ARGS"] = "1"

print("[CodeShare] Startup path detection...")

# 尝试获取脚本所在的绝对路径并验证
project_root = None

print("=" * 60)
print("[CodeShare Diagnostic] Starting up...")
print(f"[CodeShare Diagnostic] os.getcwd(): {os.getcwd()}")
print(f"[CodeShare Diagnostic] sys.argv: {sys.argv}")
print(f"[CodeShare Diagnostic] sys.path: {sys.path[:4]}")

try:
    import sys
    frame = sys._getframe(0)
    mainpyfile = None
    while frame:
        if 'mainpyfile' in frame.f_locals:
            mainpyfile = frame.f_locals['mainpyfile']
            break
        frame = frame.f_back
    print(f"[CodeShare Diagnostic] Found mainpyfile in stack: {mainpyfile}")
    if mainpyfile:
        dir_path = os.path.dirname(os.path.abspath(mainpyfile))
        print(f"[CodeShare Diagnostic] mainpyfile directory: {dir_path}")
        if os.path.exists(dir_path):
            print(f"[CodeShare Diagnostic] Contents of mainpyfile dir: {os.listdir(dir_path)}")
        else:
            print(f"[CodeShare Diagnostic] mainpyfile dir does not exist!")
except Exception as e:
    print(f"[CodeShare Diagnostic] Failed to debug mainpyfile: {e}")

print(f"[CodeShare Diagnostic] 'core' in current dir: {os.path.exists('core')}")
print("=" * 60)

def is_valid_root(path):
    return (
        path
        and os.path.isdir(path)
        and (
            os.path.isfile(os.path.join(path, 'core', 'code_share_app.py'))
            or os.path.isfile(os.path.join(path, 'code_share_app.py'))
        )
    )


def normalize_project_root(path):
    """Prefer the repository root when running from core/main.py locally."""
    if not path:
        return None
    parent = os.path.dirname(path)
    if (
        os.path.basename(path).lower() == "core"
        and os.path.isfile(os.path.join(path, "code_share_app.py"))
        and os.path.isfile(os.path.join(parent, "core", "code_share_app.py"))
    ):
        return parent
    return path

# 1. 尝试从 __file__ 获取（标准运行方式）
try:
    if '__file__' in globals() and __file__ and not __file__.startswith('<'):
        path = os.path.dirname(os.path.abspath(__file__))
        if is_valid_root(path):
            project_root = normalize_project_root(path)
            print(f"[CodeShare] Method 1 (__file__) succeeded: {project_root}")
except Exception as e:
    print(f"[CodeShare] Method 1 failed: {e}")

# 2. 尝试从调用栈获取 Pydroid 3 的 mainpyfile 局部变量（Pydroid 3 核心兼容）
if not project_root:
    try:
        frame = sys._getframe(0)
        while frame:
            locals_dict = frame.f_locals
            if 'mainpyfile' in locals_dict and locals_dict['mainpyfile']:
                candidate = locals_dict['mainpyfile']
                path = os.path.dirname(os.path.abspath(candidate))
                if is_valid_root(path):
                    project_root = normalize_project_root(path)
                    print(f"[CodeShare] Method 2 (Stack frame mainpyfile) succeeded: {project_root}")
                    break
            frame = frame.f_back
    except Exception as e:
        print(f"[CodeShare] Method 2 failed: {e}")

# 3. 尝试从 Pydroid 3 的全局变量 mainpyfile 获取
if not project_root:
    try:
        import __main__
        if hasattr(__main__, 'mainpyfile') and __main__.mainpyfile:
            path = os.path.dirname(os.path.abspath(__main__.mainpyfile))
            if is_valid_root(path):
                project_root = normalize_project_root(path)
                print(f"[CodeShare] Method 3 (__main__.mainpyfile) succeeded: {project_root}")
    except Exception as e:
        print(f"[CodeShare] Method 3 failed: {e}")

# 4. 尝试从 sys.argv[0] 获取
if not project_root:
    try:
        if sys.argv and sys.argv[0] and not sys.argv[0].startswith('<'):
            path = os.path.dirname(os.path.abspath(sys.argv[0]))
            if is_valid_root(path):
                project_root = normalize_project_root(path)
                print(f"[CodeShare] Method 4 (sys.argv[0]) succeeded: {project_root}")
    except Exception as e:
        print(f"[CodeShare] Method 4 failed: {e}")

# 5. 尝试从当前工作目录获取
if not project_root:
    try:
        path = os.getcwd()
        if is_valid_root(path):
            project_root = normalize_project_root(path)
            print(f"[CodeShare] Method 5 (getcwd) succeeded: {project_root}")
    except Exception as e:
        print(f"[CodeShare] Method 5 failed: {e}")

# 6. 向上查找（以防从子目录下运行）
if not project_root:
    search_paths = []
    try:
        search_paths.append(os.getcwd())
    except Exception:
        pass
    try:
        if sys.argv and sys.argv[0] and not sys.argv[0].startswith('<'):
            search_paths.append(os.path.dirname(os.path.abspath(sys.argv[0])))
    except Exception:
        pass
    
    # 尝试从调用栈中的任何 py 文件位置向上查找
    try:
        frame = sys._getframe(0)
        while frame:
            if '__file__' in frame.f_globals and frame.f_globals['__file__'] and not frame.f_globals['__file__'].startswith('<'):
                search_paths.append(os.path.dirname(os.path.abspath(frame.f_globals['__file__'])))
            frame = frame.f_back
    except Exception:
        pass
    
    for start_path in search_paths:
        curr = start_path
        for _ in range(5):
            if is_valid_root(curr):
                project_root = normalize_project_root(curr)
                print(f"[CodeShare] Method 6 (Recursive scan) succeeded: {project_root}")
                break
            parent = os.path.dirname(curr)
            if parent == curr:
                break
            curr = parent
        if project_root:
            break

# 7. 常见路径探测（下载或共享目录）
if not project_root:
    candidates = [
        "/storage/emulated/0/Download/challenge3",
        "/storage/emulated/0/Download/Challenge/challenge3",
        "/sdcard/Download/challenge3",
        "/sdcard/Download/Challenge/challenge3",
    ]
    for candidate in candidates:
        if is_valid_root(candidate):
            project_root = normalize_project_root(candidate)
            print(f"[CodeShare] Method 7 (Common paths) succeeded: {project_root}")
            break

# 8. 兜底使用当前工作目录
if not project_root:
    project_root = os.getcwd()
    print(f"[CodeShare] Method 8 (Fallback to getcwd) used: {project_root}")

sys.path.insert(0, project_root)

print(f"[CodeShare] Resolved project root: {project_root}")
print(f"[CodeShare] sys.path: {sys.path[:3]}")

# 调试：如果在解析的路径下找不到入口模块，输出目录内容
if not is_valid_root(project_root):
    print(f"[CodeShare] ERROR: app entry not found in resolved root '{project_root}'!")
    try:
        print(f"[CodeShare] Contents of '{project_root}': {os.listdir(project_root)}")
    except Exception as e:
        print(f"[CodeShare] Cannot list contents of '{project_root}': {e}")

try:
    from core.code_share_app import CodeShareApp
except ImportError:
    from code_share_app import CodeShareApp
import argparse

if __name__ == '__main__':
    if project_root and os.path.exists(project_root):
        os.chdir(project_root)
        
    parser = argparse.ArgumentParser(description="相识北洋社交应用")
    parser.add_argument("--port", type=int, default=7779, help="TCP Listening Port")
    parser.add_argument("--udp-port", type=int, default=8890, help="UDP Discovery Port")
    parser.add_argument("--db", type=str, default="friends.db", help="SQLite DB File")
    parser.add_argument("--name", type=str, default="", help="Username/Device name Override")
    args, unknown = parser.parse_known_args()
    
    db_path = args.db
    if db_path and not os.path.dirname(db_path):
        db_path = os.path.join("assets", "data", db_path)
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)

    CodeShareApp(
        tcp_port=args.port,
        udp_port=args.udp_port,
        db_path=db_path,
        name_override=args.name
    ).run()
