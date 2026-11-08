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

## 使用已有 Nginx

如果 Nginx 已占用 80 和 443 端口，使用回环端口配置。它只启动数据库和应用，不启动 Caddy，也不修改 Nginx。

```sh
cp compose.nginx.yaml compose.override.yaml
docker compose up -d --build db web
```

该配置将应用绑定到 `127.0.0.1:18082`，限制容器内存和日志大小，并使用一个 Gunicorn worker。`.env` 中的 `DOMAIN` 可以暂时设为 `localhost`。

接入 HTTPS 域名时，在 `.env` 的 `DJANGO_ALLOWED_HOSTS` 中加入实际域名，保留 `localhost,127.0.0.1`。将 `DJANGO_CSRF_TRUSTED_ORIGINS` 设为实际 HTTPS 来源，然后执行 `docker compose up -d web`。

Nginx 将请求转发到 `http://127.0.0.1:18082`，保留原始 `Host`，并覆盖 `X-Forwarded-Proto` 为 `$scheme`。`DJANGO_HTTPS=1` 时，Django 会启用 HTTPS 跳转和 HSTS。生产环境始终使用安全 Cookie。Nginx 负责 TLS 证书和 HTTP 跳转。客户端必须通过 HTTPS 访问，不要让客户端直接控制转发协议头。

```nginx
location / {
    proxy_pass http://127.0.0.1:18082;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_read_timeout 180s;
    client_max_body_size 10m;
}
```

初始配置关闭应用的 HTTPS 重定向和 HSTS，由前置 Nginx 控制这两项。需要由 Django 处理时，可在 `.env` 中将 `DJANGO_HTTPS` 设为 `1`，然后重启应用。应用会为该域名及其子域名发送一年有效的 HSTS；启用前应确认它们均支持 HTTPS。不要公开绑定应用端口。

```sh
curl -f http://127.0.0.1:18082/health/
curl -I http://127.0.0.1:18082/staff-access/
```

`DJANGO_HTTPS=1` 时，上面的管理员入口会跳转到 HTTPS。检查代理后的页面可使用：

```sh
curl -I -H 'Host: your-domain.example' -H 'X-Forwarded-Proto: https' http://127.0.0.1:18082/staff-access/
```

`compose.override.yaml` 会被 Docker Compose 自动加载，因此本文中的备份、恢复和更新命令仍可使用。

## 直接通过 IP 和端口访问

没有域名且不接入现有反向代理时，可通过 `http://服务器IP:18082` 直接访问应用：

```sh
docker compose -f compose.yaml -f deploy/compose.direct.yaml up -d --build
```

此模式使用明文 HTTP，仅适合临时演示或可信网络。账号密码、会话 Cookie 和学生数据不会获得传输加密。正式使用应配置 HTTPS，并保持 `DJANGO_COOKIE_SECURE=1`。

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
