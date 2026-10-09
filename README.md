# 表扬榜

多班级中文表扬榜网站。科任老师按科目填报，班主任汇总、定稿并导出图片，再发送到班级群。

## 功能

- 支持多个班级、科目、教师和任教关系。
- 教师按班级和科目填报表扬对象、项目、原因与备注。
- 表扬条目以学生姓名为标题，项目、原因与备注、科目和教师显示在标题下方。
- 班主任可以维护学生名单、补录历史日期、调整汇总内容、定稿和重新打开。
- 班主任和管理员可以导出 PNG。超过一页时返回 ZIP。
- 定稿保存独立版本和姓名快照。旧版本及已生成图片不会被新排版覆盖。
- 支持 XLSX 和 UTF-8 CSV 名单导入。导入先预览再确认，错误文件不会写入数据。
- 管理员使用独立入口管理教师、班级、科目、班主任和任教关系。
- 管理后台沿用工作台的导航和样式。选择班级后，学生名单与任教关系入口保持可见。

## 角色与权限

| 角色 | 可以做什么 |
| --- | --- |
| 管理员 | 管理教师、班级、科目、班主任、任教关系和密码；查看全站数据；导出任意班级图片 |
| 班主任 | 管理本班学生；汇总、定稿、重新打开；导出本班图片 |
| 科任教师 | 填报自己负责科目的表扬；只能修改自己当天的填报 |

管理员在“全站管理 → 班级 → 班主任”中设置班主任。班主任必须同时拥有至少一条有效任教关系，才能从教师入口登录。普通科任教师只能填报，不能导出图片。

## 本地启动

需要 Python 3.12 或更高版本。以下命令在 Windows PowerShell 中执行：

```powershell
uv venv .venv
uv pip install -r requirements.txt
.venv\Scripts\python.exe -m playwright install chromium
$env:DJANGO_DEBUG="1"
.venv\Scripts\python.exe manage.py migrate
.venv\Scripts\python.exe manage.py bootstrap_admin
.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

Linux 使用以下命令。Chromium 的系统依赖安装可能需要管理员权限：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m playwright install --with-deps chromium
export DJANGO_DEBUG=1
.venv/bin/python manage.py migrate
.venv/bin/python manage.py bootstrap_admin
.venv/bin/python manage.py runserver 127.0.0.1:8000
```

Linux 图片导出需要中文字体，例如 Debian 的 `fonts-noto-cjk`。Docker 镜像已安装该字体和 Chromium 的系统依赖。

教师入口为 `/`，管理员入口为 `/staff-access/`，管理后台为 `/staff-room/`。`bootstrap_admin` 创建的初始管理员账号是 `admin`，初始密码是 `123456`。首次登录必须修改密码。不要在实际环境中继续使用初始密码。

本地默认使用 SQLite。演示数据不会自动导入。需要合成数据时，只能在 `DJANGO_DEBUG=1` 的本地环境执行：

```powershell
.venv\Scripts\python.exe manage.py seed_demo
```

Windows 启动命令需要已安装 `uv`。也可以使用 `python -m venv .venv` 创建环境，再执行 `.venv\Scripts\python.exe -m pip install -r requirements.txt` 安装依赖。

## 账号规则

- 教师登录时先选班级，再选“科目-姓名”。同一个账号可对应多科，密码共用。同名同科账号追加账号名以区分。
- 新账号使用初始密码 `123456`，首次登录必须改密。新密码不能与原密码相同，也不能全部使用数字。密码长度和字符组合由管理员与教师自行决定。
- 只有管理员可以强制重置教师密码。重置后不再强制改密，原有登录会话因密码变更失效。管理员不能将密码重置为纯数字。
- 登录身份列表只显示所选班级的有效教师。学生、填报和图片均需要登录及班级权限。隐藏管理员入口不代替密码与服务端权限验证。

## 日常流程

1. 管理员创建科目、教师和班级，设置班主任并分配任教关系。
2. 班主任添加学生，或上传表头为“学号”和“姓名”的 XLSX／UTF-8 CSV。
3. 教师选择单人、多人或全班，填写表扬项目和原因与备注，保存草稿或提交。
4. 班主任打开当日汇总，调整名单、项目顺序、标题和落款，然后定稿。
5. 班主任预览并下载图片。多页图片以 ZIP 返回。

离班学生不会被删除，历史记录仍然保留。全班表扬保存当时的学生范围，但图片显示“全班同学”。

名单导入中，相同学号更新姓名和在读状态，文件中未出现的学生保持不变。定稿后可以重新打开并更正，旧定稿版本与已生成图片保持不变。

## 生产部署

生产环境使用 Docker Compose、PostgreSQL 和 Caddy。完整步骤见 [`deploy/README.md`](deploy/README.md)。

```sh
cp .env.example .env
# 修改 .env 中的域名、密钥、允许访问的主机和数据库密码
docker compose up -d --build
docker compose exec web python manage.py bootstrap_admin
docker compose exec web python manage.py check --deploy
```

生产环境必须设置长度至少 50 个字符的 `DJANGO_SECRET_KEY`，并配置 `DJANGO_ALLOWED_HOSTS`、`DJANGO_CSRF_TRUSTED_ORIGINS` 和数据库密码。不要提交真实 `.env` 文件。

持久化数据位于 Docker volumes：`postgres_data` 保存数据库，`board_media` 保存导出图片，`caddy_data` 和 `caddy_config` 保存证书及 Caddy 配置。备份和恢复命令见 [`deploy/README.md`](deploy/README.md)。不要执行 `docker compose down -v`，否则会删除数据卷。

## 验证

```powershell
$env:DJANGO_DEBUG="1"
.venv\Scripts\python.exe manage.py check
.venv\Scripts\python.exe manage.py test --verbosity 1
docker compose --env-file .env.example config --quiet
```

测试覆盖初始改密、管理员密码重置、身份选择、跨班权限、当天限制、定稿与历史快照、CSV／XLSX 导入、真实 Chromium 图片分页，以及桌面和手机端的主要导航与填报流程。

## 目录

- `board/`：账号、权限、填报、导入、定稿和图片渲染。
- `templates/`：教师工作台、管理员工作台和 PNG 模板。
- `static/`：本地样式、交互脚本和 Lucide 图标。
- `praiseboard/`：Django 项目配置。
- `deploy/`：Docker 启动、备份、恢复、Caddy 和部署说明。
- `design.md`：界面呈现规则。
- `PRODUCT.md`：产品范围和业务约束。

## 仓库边界

仓库只保存源码、迁移、测试、部署配置和本地静态资源。数据库、个人名单、账号、上传文件、导出图片、密钥、截图、浏览器记录和运行日志均不应提交。`.gitignore` 和 `.dockerignore` 已覆盖这些本地文件。

图标来源为 Lucide，许可证位于 `static/icons/LICENSE`。网站不依赖外部图片或在线字体。
