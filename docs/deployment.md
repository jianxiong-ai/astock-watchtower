# 部署说明

## Docker Compose

```bash
cp .env.example .env
docker compose up --build
```

默认端口：

- Web: http://localhost:3000
- API: http://localhost:8000
- API docs: http://localhost:8000/docs
- Health: http://localhost:3000/health

## 环境变量

最常改的变量：

- `NEXT_PUBLIC_API_BASE_URL`：浏览器访问 API 的地址。远程部署时必须改成公网或局域网可访问地址，并重建 web 镜像。
- `FEISHU_DEFAULT_SECRET`：飞书机器人签名密钥，可为空；单个订阅也可填写独立密钥。
- `FEISHU_MESSAGE_MODE`：`card` 或 `text`。
- `SCHEDULER_HOUR` / `SCHEDULER_MINUTE`：订阅扫描时间，默认北京时间 08:00。
- `A_SHARE_HOLIDAYS`：逗号分隔的本地休市覆盖日期，如 `2026-10-01,2026-10-02`。

## Healthcheck

Compose 内置 healthcheck：

- PostgreSQL：`pg_isready`
- Redis：`redis-cli ping`
- API：`GET /health`
- Web：`GET /health`

应用层健康检查：

```bash
python3 scripts/smoke_test.py
```

可自定义地址：

```bash
API_BASE_URL=https://api.example.com WEB_BASE_URL=https://watch.example.com python3 scripts/smoke_test.py
```

## 生产部署注意

- 请把飞书 webhook、签名密钥和数据库密码放在私有 `.env` 或部署平台 secret 中，不要提交仓库。
- 本项目默认不做用户登录；如果部署到公网，建议放在 VPN、反向代理 Basic Auth 或内网环境后面。
- 行情和公告数据源可能受网络、反爬或授权限制影响；系统会标注 Missing/Stale，但不保证完整性。
- 首次同步公告时，PDF 抽取可能较慢；可降低 `PDF_EXTRACT_MAX_PAGES` 和 `PDF_TABLE_MAX_PAGES`。
