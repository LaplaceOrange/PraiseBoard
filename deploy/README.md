# Debian 部署

需要 Debian 12 或更新版本、Docker Engine、Docker Compose 插件、指向服务器的域名，以及开放的 TCP 80 和 443 端口。PostgreSQL 和应用端口不直接对公网开放。

## 初次部署

1. 将项目放入服务器的固定目录，例如 `/opt/praiseboard`。
2. 从 `.env.example` 创建 `.env`。
3. 修改域名、允许访问的主机、HTTPS 来源、数据库密码和 Django 密钥。

生成随机密钥：

```sh
openssl rand -hex 32
```

`.env` 中的 `DJANGO_ALLOWED_HOSTS` 必须保留 `localhost,127.0.0.1`，以便容器健康检查工作。`DJANGO_CSRF_TRUSTED_ORIGINS` 使用完整 HTTPS 来源，例如 `https://praise.example.com`。

4. 限制 `.env` 文件权限。

```sh
chmod 600 .env
```

5. 构建并启动容器。

```sh
docker compose up -d --build
docker compose ps
docker compose logs --tail=100 web
```

应用启动时执行数据库迁移。Caddy 在域名解析正确且端口开放后申请并续期 HTTPS 证书。镜像安装 Chromium 与中文字体，首次构建需要联网下载依赖。

图片渲染会启动 Chromium。建议至少准备 2 GB 内存，并按实际教师同时使用量调整服务器容量。

6. 创建管理员。

```sh
docker compose exec web python manage.py bootstrap_admin
```

使用 `/staff-access/` 登录。初始账号为 `admin`，初始密码为 `123456`。首次登录必须改密，然后创建教师、班级、科目和任教关系。

7. 执行部署检查。

```sh
docker compose exec web python manage.py check --deploy
```

HSTS preload 默认关闭，检查可能提示可选的 `security.W021`。不应仅为消除该提示而申请整个域名的浏览器预加载。

默认管理员入口不在教师登录页显示。它仍使用密码验证，不应视为安全边界。不要将默认密码留给已投入使用的账号。

## 持久化

`postgres_data` 保存数据库，`board_media` 保存导出图片，`caddy_data` 保存证书。不要执行 `docker compose down -v`，该命令会删除这些数据卷。

## 备份与恢复

备份脚本会短暂停止应用，确保数据库与图片属于同一份备份。数据库容器保持运行。

```sh
sh deploy/backup.sh /srv/praiseboard-backups
```

将数据库文件和对应图片压缩包共同保存。定期复制到服务器之外的受控位置。

恢复前先保存当前备份。恢复脚本需要手动输入 `RESTORE`，并会替换数据库内容。

```sh
sh deploy/restore.sh /srv/praiseboard-backups/DATE.database.dump /srv/praiseboard-backups/DATE.media.tar.gz
```

建议在独立环境定期演练恢复，并核对账号、班级、定稿版本和图片下载。

## 更新

```sh
sh deploy/backup.sh /srv/praiseboard-backups
docker compose up -d --build
docker compose exec web python manage.py check --deploy
```

不要在未经验证的数据库迁移后仅替换旧镜像。需要回退时，使用匹配的代码版本和备份恢复。

## 排错

```sh
docker compose ps
docker compose logs --tail=200 web
docker compose logs --tail=100 caddy
docker compose exec web python manage.py check
```

图片生成失败时检查应用日志、容器内存和 Chromium 安装。未启动完成时先检查数据库健康状态。日志不输出教师密码或学生名单。
