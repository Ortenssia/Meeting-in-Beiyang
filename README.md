# 相识北洋（Meeting in Beiyang）

“相识北洋”是一个使用 Python 与 Flet 开发的校园局域网社交应用，对应 Challenge 3。

当前版本：`1.8.95`

应用通过 UDP 在局域网内发现附近用户，并使用 TCP 建立好友间的点对点连接，支持好友申请、资料匹配、即时聊天、离线消息中继和文件传输。

## 主要功能

- 通过 UDP 广播与主动扫描发现局域网用户
- 好友之间建立 TCP 点对点连接
- 编辑并持久化昵称、头像、简介和兴趣标签
- 配置好友匹配条件，支持手动或自动同意好友申请
- 好友搜索、分类、删除和在线状态显示
- 保存聊天记录，并在头像上显示未读消息红点
- 聊天窗口收到或发送新消息后自动滚动到底部
- 文件分块传输、SHA-256 完整性校验和断点续传
- 自定义接收文件保存目录，并持久化本地设置
- 文件卡片支持打开文件、定位目录、复制路径、取消、重试和解压 ZIP
- 好友离线时缓存消息，并通过在线好友进行有限跳数的中继

## 获取与更新仓库

### 方法一：使用 Git 克隆与更新（推荐）

#### 首次下载

安装 [Git](https://git-scm.com/) 后，在终端中克隆仓库：

```powershell
git clone https://github.com/Ortenssia/Meeting-in-Beiyang.git
cd Meeting-in-Beiyang
```

#### 后续更新

在项目根目录下执行以下命令拉取最新代码：

```powershell
git pull origin main
```

**若本地有代码修改或文件冲突导致 `git pull` 失败，可以使用以下命令强制覆盖本地代码进行更新（本地保存的好友数据、接收的文件不受影响）：**

```powershell
git fetch --all
git reset --hard origin/main
```

---

### 方法二：不使用 Git 下载（下载 ZIP 压缩包）

#### 首次下载

1. 打开 [GitHub 仓库页面](https://github.com/Ortenssia/Meeting-in-Beiyang)。
2. 点击绿色的 **Code** 按钮，选择 **Download ZIP**。
3. 将下载的压缩包解压到本地目录。

#### 后续更新

当仓库有新更新时，请**不要直接用新解压的整个文件夹完全覆盖老文件夹**，以防抹去本地产生的好友数据库和下载文件。
请按照以下步骤安全更新：
1. 再次下载最新的 ZIP 压缩包并解压。
2. 将解压出来的 `core/` 目录以及根目录下的 `requirements.txt` 等代码文件复制并**覆盖**到你原有的本地目录中。
3. **请不要覆盖或删除本地目录中的 `.runtime/` 文件夹以及 `assets/data/friends.db` 文件**，这两个位置保存了你的所有聊天记录、已添加的好友和身份设置。

## 环境安装

推荐使用 Python 3.10 或更高版本。在项目根目录执行：

```powershell
python -m pip install -r requirements.txt
```

建议使用虚拟环境：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## 运行应用

### Windows 一键启动（推荐）

双击 `run.bat`，脚本会自动：

1. 检测 Python 3.10 或更高版本；
2. 在项目目录创建隔离的 `.venv`；
3. 仅在依赖缺失时安装依赖；
4. 启动应用。

也可以在 PowerShell 中运行，并附加启动参数：

```powershell
.\run.bat --name Alice --port 7779 --udp-port 8890
```

首次启动需要联网安装依赖。不要将其他电脑上的 `.venv` 复制过来，每台电脑应自行生成。

### 命令行启动

普通启动：

```powershell
python core/main.py
```

指定昵称、TCP 端口、UDP 端口和数据库：

```powershell
python core/main.py --port 7779 --udp-port 8890 --db friends.db --name Alice
```

使用 `--log-level DEBUG` 可以输出更详细的网络和框架日志：

```powershell
python core/main.py --log-level DEBUG
```

## 本机双实例测试

在同一台电脑上分别启动 Alice 和 Bob：

```powershell
python core/main.py --instance alice --name Alice --port 7779 --udp-port 8890
python core/main.py --instance bob --name Bob --port 7780 --udp-port 8891
```

也可以使用脚本一次启动两个实例：

```powershell
powershell -ExecutionPolicy Bypass -File operations/run_local_pair.ps1
```

`--instance` 会为每个进程创建隔离的数据库、文件接收目录和头像缓存，路径位于 `.runtime/<instance>/`。两个实例必须使用不同的 TCP 和 UDP 监听端口，但共享项目中的字体、图标和默认头像资源。

## 界面与数据路径

应用使用 [Flet](https://flet.io) 构建界面，采用 Material 3 风格并跟随系统明暗主题。

- `core/frontend/` 只负责界面、交互和 App 层调用
- `core/backend/services/` 负责 UDP、TCP、好友关系、消息和文件传输
- `core/config/paths.py` 统一解析数据库、资源和文件接收路径
- `BEIYANG_DATA_DIR` 可以覆盖本地数据目录
- `BEIYANG_RECEIVED_DIR` 可以覆盖默认文件接收目录

不要在界面或网络服务中硬编码数据库、字体、图片和文件接收路径。

## 项目结构

```text
core/                       应用代码
  config/                   路径和平台配置
  frontend/                 Flet 界面与 App 控制器
    views/                  发现、好友、聊天、动态、资料和设置页面
  backend/
    services/               UDP、TCP、好友、消息、文件和运行时服务
    shared/                 协议、网络工具和共享消息格式
  ops/                      启动准备与日志配置
assets/                     图标、字体和默认头像等资源
operations/                 本地运行与双实例测试脚本
core/main.py                应用入口
requirements.txt            Python 依赖列表
```

## 架构说明

`core` 是应用代码边界，各层职责如下：

- 前端层：`core/frontend/` 构建 Flet 控件，通过 `BeiyangApp` 调用应用功能，不直接操作 UDP、TCP 或 SQLite。
- 服务层：`core/backend/services/` 管理身份、用户发现、好友关系、消息中继、文件传输和生命周期。
- 共享层：`core/backend/shared/` 保存协议常量、网络工具和前后端共享的消息格式。
- 配置层：`core/config/` 统一管理项目资源路径和可写数据路径。
- 运维层：`core/ops/` 负责导入环境、工作目录和日志初始化。

文件相关职责进一步拆分为：

- `file_store.py`：文件名安全处理、路径冲突处理和哈希计算
- `file_transfer_state.py`：发送、接收、取消和续传的运行时状态
- `file_message.py`：前后端共享的文件消息编码与解析格式

页面应优先调用 App 层公开方法，不应直接依赖后端服务的内部字典、锁或数据库连接。
