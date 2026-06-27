# 备份与恢复

`astock-watchtower` 的关键数据包括：

- 订阅配置
- 飞书 webhook 和签名密钥
- 交易记录
- 持仓计算所依赖的历史流水
- 公告、PDF 抽取结果、结构化事实
- 推送/试运行日志

发布或升级前建议先备份数据库。

## SQLite 本地开发备份

默认本地开发数据库位于项目根目录：

```bash
astock_watchtower.sqlite3
```

备份：

```bash
cp astock_watchtower.sqlite3 "astock_watchtower.backup.$(date +%Y%m%d-%H%M%S).sqlite3"
```

恢复：

```bash
cp astock_watchtower.backup.YYYYMMDD-HHMMSS.sqlite3 astock_watchtower.sqlite3
```

恢复前请先停止 API 服务，避免运行中写入。

## Docker Compose / PostgreSQL 备份

查看容器：

```bash
docker compose ps
```

备份：

```bash
docker compose exec db pg_dump -U postgres astock_watchtower > "astock_watchtower.backup.$(date +%Y%m%d-%H%M%S).sql"
```

恢复前先停止 API/Web，避免写入：

```bash
docker compose stop api web
```

恢复：

```bash
cat astock_watchtower.backup.YYYYMMDD-HHMMSS.sql | docker compose exec -T db psql -U postgres astock_watchtower
```

恢复后重启：

```bash
docker compose up -d
```

## 敏感信息

数据库可能包含飞书 webhook 和签名密钥。备份文件请视为敏感文件：

- 不要提交到 Git。
- 不要上传到公开网盘。
- 如果需要共享问题复现，请先脱敏。

## 升级前检查

升级或拉取新版本前建议：

1. 备份数据库。
2. 导出 `.env` 或记录关键配置。
3. 运行当前版本 smoke test，确认升级前是健康状态。
4. 升级后运行：

```bash
make api-test
make web-build
python3 scripts/smoke_test.py
```

如果升级后数据异常，先停止服务，再从备份恢复。
