# astock-watchtower 第一版发布前 Checklist

这份清单用于判断第一版是否已经达到“可以给别人自托管运行”的状态。它不追求覆盖所有专业投研能力；第一版目标是稳定跑通订阅、持仓、手动分析、公告证据、数据质量提示和飞书推送闭环。

## 0. 发布边界

第一版定位：

- 个人自托管 A 股订阅与分析工具。
- 订阅最多 3 只股票，支持本地交易记录和飞书 webhook。
- 手动分析支持任意 A 股临时查询，不自动保存为订阅。
- 输出区分官方来源、二级来源、Stale Sources 和 Missing Inputs。
- 不连接券商，不执行交易，不保证行情实时性，不构成投资建议。

Public Equity Investing 的使用边界：

- 只借鉴其公开股市分析流程：交易日判断、官方披露优先、行业分层、验证链、Missing/Stale 显式化、持仓感知建议。
- 不把 Codex 插件作为运行时依赖。
- 不同步插件中的 watchlist、持仓、自动化或私有上下文。
- 不要求用户安装、登录或配置 Public Equity Investing。

## 1. 环境变量检查

发布前复制 `.env.example` 为 `.env`，逐项确认：

- `DATABASE_URL`
  - Docker 发布建议使用 PostgreSQL。
  - 本地开发可使用默认 SQLite。
- `NEXT_PUBLIC_API_BASE_URL`
  - 必须是浏览器能访问到的 API 地址。
  - 改完后必须重新构建 Web。
- `API_CORS_ORIGINS`
  - 必须包含 Web 站点地址。
- `FEISHU_MESSAGE_MODE`
  - 默认 `card`。
  - 如飞书卡片失败，可临时切换为 `text`。
- `SCHEDULER_TIMEZONE`
  - 默认 `Asia/Shanghai`。
- `SCHEDULER_HOUR` / `SCHEDULER_MINUTE`
  - 默认北京时间 08:00。
- `A_SHARE_HOLIDAYS`
  - 如官方休市来源短时失败，可手工补充特殊休市日期。

验收标准：健康检查页能显示关键配置，且不暴露飞书密钥。

## 2. 安装与构建

后端：

```bash
cd apps/api
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

前端：

```bash
cd apps/web
npm install
npm run build
```

验收标准：

- `pip install -r requirements.txt` 成功。
- `npm run build` 成功。
- 前端构建时没有 TypeScript 阻塞错误。

## 3. 自动化测试

在项目根目录执行：

```bash
make api-compile
make api-test
make web-build
```

或手动执行：

```bash
PYTHONPYCACHEPREFIX=/tmp/astock_pycache PYTHONPATH=apps/api apps/api/.venv/bin/python -m compileall apps/api/app apps/api/tests
PYTHONPATH=apps/api apps/api/.venv/bin/python -m pytest apps/api/tests -q
cd apps/web && npm run build
```

验收标准：

- 后端编译通过。
- 后端 pytest 全部通过。
- 前端生产构建通过。

当前已验证基线：

- 后端 pytest：`13 passed`
- 前端 `npm run build`：通过
- 后端 `compileall`：通过

## 4. 本地端到端验收

启动 API：

```bash
cd apps/api
PYTHONPATH=. .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

启动 Web：

```bash
cd apps/web
npm run start
```

运行 smoke test：

```bash
python3 scripts/smoke_test.py
```

验收标准：

- API `/health` 返回 ok。
- API `/api/system/health` 可访问。
- API `/api/scheduler/status` 显示 scheduler 状态。
- Web 首页可访问。
- Web `/health` 可访问。
- Web `/subscriptions` 可访问。
- Web `/analysis` 可访问。

允许的 warning：

- `trading_calendar=warning`：如果官方休市来源部分可用但不完整，系统必须明确说明 warning、官方来源和本地兜底策略。

不允许的失败：

- API 启动失败。
- Web 构建失败。
- 数据库连接失败。
- `/api/system/health` 整体 failed。
- 前端只显示浏览器原始 `TypeError: Failed to fetch`，而没有可读提示。

## 5. 订阅功能验收

在订阅页完成：

- 新增 1 只 A 股订阅。
- 最多启用 3 只订阅；第 4 只启用应被阻止。
- 编辑显示名称。
- 编辑飞书 webhook；签名密钥不回显。
- 暂停/启用订阅。
- 删除订阅前出现二次确认。

验收标准：

- 订阅 CRUD 正常。
- 飞书 webhook URL 前端校验有效。
- 删除订阅不会删除交易流水。

## 6. 交易记录与持仓验收

手工新增：

- 新增买入交易。
- 新增卖出交易。
- 编辑交易。
- 删除交易前出现二次确认。

Excel 导入：

- 导入正常文件。
- 导入包含错误行的文件。
- 导入缺少必要列的文件。

验收标准：

- 持仓股数、移动加权成本、已实现盈亏、未实现盈亏可计算。
- Excel 导入展示总行数、成功数、失败数、跳过空行数、股票分布、方向分布、失败行预览。
- 行情失败时仍展示可由交易流水计算的持仓，并把行情缺失写入 warning。

## 7. 手动分析验收

在分析页输入：

- `贵州茅台`
- `600362.SH`
- `601336.SH`
- 至少 1 只非白酒/有色/保险行业股票，例如银行、券商、医药、电子、新能源/电池或家电/消费制造。

验收标准：

- 能识别股票代码、交易所、公司名称和行业。
- 返回行情快照、估值、技术指标、市场天气。
- 返回公告事件和官方/二级来源链接。
- 返回行业骨架与 Missing Inputs。
- 无持仓基线时，不编造股数、成本、盈亏或具体交易手数。

## 8. 定时推送与飞书验收

本地试运行：

```bash
curl -X POST http://localhost:8000/api/scheduler/run-now \
  -H 'Content-Type: application/json' \
  -d '{"send": false, "force_notify": true}'
```

真实飞书测试：

- 在订阅页填入飞书 webhook。
- 点击“测试推送”。
- 只对自己的测试群发送。

真实飞书试运行：

```bash
curl -X POST http://localhost:8000/api/scheduler/run-now \
  -H 'Content-Type: application/json' \
  -d '{"send": true, "force_notify": true}'
```

验收标准：

- 非交易日能正确跳过订阅扫描。
- 交易日能返回每个订阅的结构化报告。
- `send=false` 不发送飞书。
- `send=true` 只发送到用户配置的 webhook。
- 推送/试运行日志能在订阅页刷新后看到。
- 卡片模式失败时能降级为文本模式。

## 9. 公告、PDF 和结构化事实验收

使用抽取质量页或 API：

```bash
curl -X POST http://localhost:8000/api/announcements/quality \
  -H 'Content-Type: application/json' \
  -d '{"symbol": "600519.SH", "days": 180, "sync": true}'
```

验收标准：

- 能同步上交所/深交所官方公告。
- 能展示公告分类、重要性、摘要、影响层和下一证据。
- PDF 抽取成功时展示正文/表格/结构化事实。
- PDF 抽取失败时展示 `pdf_extract_status` 和错误原因，不伪造正文。
- 财报结构化字段缺失时进入 Missing Inputs。

## 10. 数据质量验收

在分析结果、推送预览和健康检查中确认：

- Official 和 Secondary 来源分开标注。
- Stale Sources 和 Missing Inputs 分开显示。
- 每个 Missing/Stale 至少包含：
  - 指标
  - 最后已知日期，如有
  - 尝试来源
  - 首选来源
  - 对判断的影响
  - 下一来源

验收标准：不能用笼统一句话替代具体缺失项，不能用无来源估计值填空。

## 11. 第一版功能补充评估

发布前建议补充，但不阻塞第一版：

1. 数据备份/恢复说明
   - 已补充 `docs/backup.md`。
   - 覆盖 SQLite 本地开发和 Docker Compose / PostgreSQL 两种场景。

2. 示例 Excel 模板
   - 已补充 `examples/trades_template.csv`。
   - CSV 可直接用 Excel 打开，也适合开源仓库版本管理。

3. 真实飞书推送截图/说明
   - 当前功能可用，但没有图示。
   - 建议发布前补一张脱敏截图或说明卡片字段。

4. Docker Compose 真实验收
   - 已在本机 Docker Desktop 验收。
   - `docker compose up -d --build` 成功。
   - API / Web / PostgreSQL / Redis 容器均为 healthy。
   - `python3 scripts/smoke_test.py` 通过。
   - 数据库类型：`postgresql+psycopg`。
   - 调度器正常运行，下一次运行时间：`2026-06-29T08:00:00+08:00`。
   - 当前唯一 warning：`trading_calendar=warning`，原因是 SZSE 年度休市通知未完整抓取，但系统已显示官方来源、警告和兜底说明。

5. 数据源 provider 抽象
   - 当前已在 README 写后续方向。
   - 不建议作为第一版阻塞项；否则会拖慢发布。

6. 用户认证
   - 自托管个人工具第一版可不做。
   - 如果公网部署，建议通过反向代理、VPN、Basic Auth 或后续内置登录保护。

7. AI 摘要 provider
   - 当前没有接入大模型 API，摘要和建议以规则为主。
   - 第一版不必接入；后续可作为用户自带 key 的可选功能。

建议第一版发布前必须补充：

- 数据备份/恢复说明。已完成。
- 示例交易记录模板。已完成。
- Docker Compose 真实启动验收记录。已完成。

建议第一版发布后迭代：

- 多数据源 provider。
- 行业指标插件化。
- AI 摘要 provider。
- 用户认证/多用户。
- 更完整的财报表格解析。

## 12. 发布判定

可以发布第一版，当且仅当：

- 自动化测试通过。
- 本地端到端 smoke test 通过。
- 订阅、交易、分析、健康检查页面可访问。
- 至少一次手动分析成功。
- 至少一次试运行推送成功返回结构化报告。
- README、部署文档、Public Equity Investing 边界文档和本 checklist 已更新。
- 已知 warning 均有解释和用户可采取的下一步。

如果出现以下情况，暂缓发布：

- 数据库迁移或启动失败。
- 订阅或交易记录会丢数据。
- 飞书 webhook 密钥泄露或明文回显。
- 数据源失败时系统编造数据。
- 手动分析把任意 A 股误保存为订阅。
- 定时推送不区分交易日/非交易日。
