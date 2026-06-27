# astock-watchtower

自托管的 A 股订阅与分析工具。

项目目标是把“定时订阅推送”和“手动个股分析”做成一个可运行的网站：

- 订阅：最多订阅 3 只 A 股，维护交易记录，配置飞书 webhook，每个交易日定时推送触发型提醒。
- 分析：临时输入任意 A 股，输出通用指标、行业特有指标、市场天气、公告事件、Stale Sources 和 Missing Inputs；若该股票已在订阅池中，会结合本地持仓基线输出盘中持仓操作建议。

> 免责声明：本项目仅用于个人研究、数据整理和提醒，不构成投资建议，不执行交易，不保证数据完整性、准确性或实时性。请遵守所使用数据源的授权条款。

## 当前 MVP

第一版先提供可运行骨架：

- FastAPI 后端
  - 订阅 CRUD，限制最多 3 只股票
  - 交易记录 CRUD
  - Excel 交易记录上传
  - 持仓计算：股数、移动加权成本、已实现/未实现盈亏
  - 持仓感知操作建议：基于仓位权重、浮盈亏、市场天气、技术触发、公告和数据质量输出保守规则建议
  - 定时任务：交易日检查、订阅扫描、触发型飞书推送
  - 官方公告抓取、入库、去重和规则分类
  - 手动发送当前分析推送到飞书
  - 任意 A 股手动分析接口
  - 市场天气 v2：A 股市场宽度、涨跌停、全市场成交额、行业涨跌/资金流、港股/美股/商品上下文
  - 行业 provider v1.4：把外部行业读数以统一结构注入行业骨架；首批支持有色/矿业的铜价、铜链板块温度和自定义 CSV 铜链数据，保险的同业表现、保险板块温度、中国 10 年国债收益率和 A/H 溢价近似计算；另支持通用 `custom_metrics.csv` 为任意股票/行业注入用户自带指标；并提供网页管理入口上传、下载、预览和校验自定义 CSV；不可得字段仍明确写入 Missing Inputs
  - 系统健康检查：数据库、调度器、交易日历、关键配置和数据源状态
- Next.js 前端
  - 单页工作台：订阅 / 分析切换；数据质量、健康检查和行业数据源管理作为高级入口默认隐藏
  - 订阅页面：订阅配置 / 持仓交易两段式 Tabs
  - 页面级流程提示：先配置订阅，再维护持仓交易；可从订阅卡片手动发送当前分析推送
  - 订阅配置在线编辑、启用/暂停、手动发送当前分析推送
  - 交易记录 Excel 导入、在线新增、编辑、删除
  - 组合与交易总览、按股票筛选最近交易流水
  - 分析页面
  - 抽取质量页面
  - 健康检查页面
- Docker Compose
  - API
  - Web
  - PostgreSQL
  - Redis（预留给定时任务/队列）

## 快速启动

复制环境变量：

```bash
cp .env.example .env
```

启动：

```bash
docker compose up --build
```

访问：

- Web: http://localhost:3000
- API: http://localhost:8000/docs
- 健康检查: http://localhost:3000/health

推荐启动后跑一次自检：

```bash
python3 scripts/smoke_test.py
```

也可以使用 Makefile：

```bash
make up
make smoke
make down
```

Docker Compose 已配置 healthcheck：

- PostgreSQL：`pg_isready`
- Redis：`redis-cli ping`
- API：`GET /health`
- Web：`GET /health`

如果要部署到远程服务器或域名，注意 `NEXT_PUBLIC_API_BASE_URL` 是前端构建期变量。请先在 `.env` 中改成浏览器可访问的 API 地址，再执行 `docker compose build web` 或 `docker compose up --build`。

## 本地开发

后端：

```bash
cd apps/api
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

前端：

```bash
cd apps/web
npm install
npm run dev
```

本地验证：

```bash
make api-compile
make api-test
make web-build
```

如果不使用 Makefile，可分别执行：

```bash
PYTHONPYCACHEPREFIX=/tmp/astock_pycache PYTHONPATH=apps/api apps/api/.venv/bin/python -m compileall apps/api/app
cd apps/api && .venv/bin/python -m pytest
cd apps/web && npm run build
```

## 常见部署问题

- 页面能打开但 API 请求失败：检查 `NEXT_PUBLIC_API_BASE_URL` 是否是浏览器可访问地址；改完后需要重建 web 镜像。
- 健康检查显示 scheduler warning：如果是直接 import 函数或未通过 FastAPI 启动，这是预期；用 `docker compose up` 或 `uvicorn app.main:app` 启动后会注册调度器。
- 交易日历 warning：说明官方交易日历有部分读取失败，系统会明确写出兜底来源；可临时用 `A_SHARE_HOLIDAYS=YYYY-MM-DD` 覆盖特殊休市。
- 公告 PDF 显示 `not_pdf_response`：通常是交易所返回了非标准 PDF 内容；上交所常见的 `acw_sc__v2` JS/cookie challenge 已支持自动计算 cookie 后重试。

## Excel 交易记录格式

交易记录有两种维护方式：

- 订阅页在线新增、编辑、删除单条交易记录。
- 上传 `.xlsx` 批量导入。

上传文件推荐列名：

| 列名 | 示例 | 说明 |
| --- | --- | --- |
| symbol | 600519.SH | 股票代码 |
| trade_date | 2026-06-26 10:30:00 | 成交时间 |
| side | buy / sell | 方向 |
| price | 1178.00 | 成交价 |
| quantity | 100 | 股数 |
| fee | 5.00 | 费用，可为空 |
| note | 手动导入 | 备注，可为空 |

也会兼容部分中文列名：股票代码、成交时间、方向、价格、数量、费用、备注。

仓库提供了一个可直接用 Excel 打开的示例模板：[trades_template.csv](examples/trades_template.csv)。

Excel 导入会返回质量反馈：

- 总行数、成功导入数、失败数、跳过空行数。
- 导入股票分布、买入/卖出分布、日期范围。
- 失败行预览：Excel 行号、失败原因和原始内容，最多展示前 20 条。
- 缺少必要列时会整体拒绝导入；单行格式错误时会跳过该行并继续导入其他有效行。

订阅页面还会展示：

- 两段式 Tabs：订阅配置、持仓交易，避免所有功能堆在一页；高级数据质量/健康检查入口默认隐藏。
- 组合总览：订阅数、持仓市值、成本金额、浮盈亏、已实现盈亏、合计盈亏。
- 分股票交易统计：交易数、买入/卖出次数、买入金额、卖出金额、费用。
- 最近交易流水：支持按订阅股票筛选。
- 单只股票卡片内最近 20 条交易：可直接编辑或删除。

## 持仓计算

后端提供 `/api/positions`，根据交易记录计算当前持仓：

- 买入：成交金额 + 费用计入成本。
- 卖出：按移动加权平均成本结转，费用从卖出收入中扣除。
- 输出：股数、平均成本、成本金额、已实现盈亏、最新价、市值、未实现盈亏、合计盈亏。
- 若行情源不可用，仍返回交易流水可计算的持仓、成本和已实现盈亏，并在 `warnings` 标明行情缺失。

订阅推送会在有持仓基线时额外输出“持仓与操作建议”：

- 输入：持仓股数/成本/浮盈亏、组合内估算权重、市场天气、行情涨跌幅、技术信号、公告触发、Stale/Missing 数量。
- 输出：`持有` / `等待确认` / `分批减仓` / `条件式加仓` 四类主姿态，以及触发条件、失效条件、主要风险、下一决策点和可执行的 A 股整手数量范围。
- 原则：不会因为价格低于成本就机械补仓；当数据缺失、市场偏冷或仓位集中时，默认偏向等待确认或控制集中度。
- 边界：这是规则化研究提醒，不是自动交易；系统不会连接券商下单。

## 定时推送

后端启动时会注册订阅扫描任务：

- 默认排程：周一至周五，北京时间 08:00。
- API 状态：`GET /api/scheduler/status`
- 推送日志：`GET /api/scheduler/logs?limit=30`，返回原始消息和从晨会报告中解析出的 `message_brief`。
- 订阅页可在线编辑显示名称、飞书 webhook、签名密钥，并可启用/暂停单个订阅。
- 前端会预校验启用订阅数量、飞书 webhook URL、交易日期、价格、数量和费用；后端错误会转换为更可读的提示。
- 数据源或后端不可用时，前端会统一提示 API 地址、连接状态或后端返回的字段级错误，避免只显示浏览器原始 TypeError。
- 后端诊断接口：`POST /api/scheduler/run-now`
  - `{"send": false, "force_notify": true}`：只生成预览，不发送飞书。
  - `{"send": true, "force_notify": false}`：按真实触发逻辑发送飞书。

订阅页卡片内的“测试推送”会生成当前股票分析报告并发送到该订阅配置的飞书 webhook；它用于核对真实推送内容，不改变正式定时任务或触发规则。后端诊断接口返回两层结果：

- `message_preview`：飞书纯文本预览，用于核对最终消息内容。
- `report_sections` / `action_advice` / `position`：结构化报告、持仓建议和持仓快照。

推送日志来自已有 `push_logs` 表，可通过 API 查看最近日志，包括状态、触发摘要、错误信息、消息内容和网页端晨会摘要预览。订阅页会把最近推送按“结论、市场温度、今日只看 3 件事、操作纪律、数据边界”展示，完整原文默认折叠，便于不用打开飞书也能核对推送质量。

交易日判断使用官方来源优先策略：

- 上交所：抓取官方“休市安排”页面。
- 深交所：抓取官方“本所公告”分页中的休市安排公告。
- 本地兜底：`.env` 的 `A_SHARE_HOLIDAYS` 可补充临时休市或手工覆盖。

如果官方来源短时不可用，系统会退回周末 + `A_SHARE_HOLIDAYS` 判断，并在 `calendar_warning` 中明确标注，不会静默伪装成官方结论。

订阅扫描会同步最近 `ANNOUNCEMENT_LOOKBACK_DAYS` 天的官方公告。新增公告会作为触发项进入飞书消息；已入库公告不会重复触发。

分析证据会使用单独的 `ANALYSIS_ANNOUNCEMENT_LOOKBACK_DAYS`，默认 180 天，用于补齐最近一期定期报告、权益分派和业绩预告等结构化事实。这个长窗口只服务分析证据，不作为“新增公告触发”窗口，避免旧公告在首次部署时刷屏。

## 官方公告

后端提供官方公告 API：

- 刷新某只股票公告：`POST /api/announcements/refresh`
- 查看已入库公告：`GET /api/announcements?symbol=600362.SH`
- 查看结构化事实：`GET /api/announcements/facts?symbol=000001.SZ`
- 检查抽取质量：`POST /api/announcements/quality`

当前支持：

- 上交所：官方上市公司公告查询接口。
- 深交所：官方 `annList` 公告接口。
- 规则分类：定期报告、业绩预告/快报、权益分派/分红、股东大会、管理层/治理、监管/处罚、重大交易/投资、融资/资本动作、担保/诉讼/风险等。
- 事件判断：为公告生成 `high / medium / watch` 重要性、基于标题/分类的规则摘要、影响层、为什么重要、下一证据。
- PDF 正文与表格抽取：下载官方 PDF，支持处理上交所 `acw_sc__v2` JS/cookie challenge；使用 `pypdf` 抽取正文，使用 `pdfplumber` 抽取前若干页表格，保存页数、字数、表格数量、正文片段、表格片段和结构化摘要。
- 结构化事实：支持权益分派公告，抽取每 10 股派息、股权登记日、除权除息日、派息日、总股本、送股/转增等字段；支持业绩预告/快报，抽取报告期、归母净利润预告区间、同比变化区间、变动方向、原因说明和正式报告披露日期等字段；支持定期报告核心表格，抽取报告期、资产、负债、权益、货币资金、短期借款、资产负债率、收入、归母净利润、扣非归母、销售/研发/财务费用、经营现金流、EPS、ROE 及可识别的同比/期末变化。
- 行业专属字段抽取增强：在定期报告表格中继续识别银行存款/贷款、净息差、不良贷款率、拨备覆盖率、核心一级/一级/资本充足率；保险保费或保险业务收入、投资收益率、核心/综合偿付能力充足率；白酒/通用消费的毛利率和合同负债；有色/制造类的存货、资本开支现金流出和规则计算自由现金流；地产、半导体/电子、医药、公用/能源等行业可复用负债、现金、费用、库存、capex 和现金流字段。
- 抽取质量调试：网站提供“抽取质量”页面，可输入股票查看公告同步状态、PDF 抽取状态、表格数量、每份公告抽出的字段、字段来源片段、行业映射覆盖率和质量警告，便于迭代解析规则。
- 分析和订阅推送会读取已入库结构化事实，并在“官方结构化事实/行业骨架与缺口”中展示最新证据；没有可靠字段时继续明确标记 Stale Sources 或 Missing Inputs。
- 行业专属指标映射：把通用财报/分红/业绩预告事实映射到白酒、保险、有色/矿业、银行、券商、地产、半导体/电子、新能源/电池、家电/消费制造、医药、公用/能源和通用行业骨架，逐项输出 Available / Partial / Missing、最新读数、证据来源、重要性和下一证据。尚未解析的行业专属字段（如保险 NBV/EV/CSM、有色 TC/RC/单位成本、券商两融/投行储备、地产销售/交付、半导体订单/稼动率、新能源出货/装机/产能利用率、家电渠道库存/终端动销、医药管线/集采、公用能源电价/利用小时）会进入 Missing Inputs，而不是用通用财务字段替代。
- 行业 provider v1.4：在财报/公告抽取之外，为行业骨架补充外部读数。当前首批 provider 包括：
  - 有色/矿业：Sina/Yahoo 商品上下文中的伦铜/COMEX 铜、Eastmoney 行业板块中的有色/能源金属/铜链温度；支持通过 `data/industry_providers/copper_chain.csv` 自定义补充 TC/RC、LME/SHFE/COMEX 库存、现货升贴水、期限价差和进口盈亏。没有自定义数据时，这些字段仍明确 Missing。
  - 保险：Sina 二级行情中的中国人寿、中国平安、中国太保、中国人保同业表现，Eastmoney 保险板块温度；ChinaMoney/中国货币网政府债券利率历史数据中的 1 年/10 年国债收益率；Sina A/H 行情和 HKD/CNY 汇率用于近似计算 A/H 溢价。若 A/H/FX 时间戳不完全一致，会标记为 Partial 并写出口径。
  - 通用自定义指标：支持通过 `data/industry_providers/custom_metrics.csv` 给任意股票或行业注入用户自带指标，例如白酒批价、渠道库存、保险代理人活动率、半导体订单、医药管线节点等。
  - provider 输出会与官方披露映射合并：当官方披露缺失而 provider 有可用读数时补齐解释层；当官方披露已有更强证据时，不用 provider 的 Missing 覆盖它。
  - 网页管理：开启首页“显示高级”后进入“行业数据”，可下载示例 CSV、上传/替换当前 CSV、预览前若干行、查看必要列校验错误，或删除当前自定义文件。上传的数据仅保存在自托管实例的 `data/industry_providers/` 挂载目录，不会提交到开源仓库。
- 行情估值、技术指标与市场天气：分析和订阅推送展示行情快照、总市值/流通市值、PE、PB、换手率、MA5/10/20/60/120、RSI14、20/60 日高低、近期高点回撤、成交量/20日均量和技术触发信号。市场天气会综合主要 A 股指数、A 股市场宽度、涨跌停、全市场成交额、行业涨跌/资金流、港股/美股和商品上下文。行情主快照使用 Sina 二级源，估值和 K 线优先使用 Eastmoney 二级源，失败时 fallback 到 Tencent 二级源；不可得时明确写入 Missing/Stale。
- 统一报告骨架：后端生成 `report_sections`，包括结论摘要、市场快照、估值与技术、行业骨架、官方公告与结构化事实、Stale/Missing。手动分析页和订阅推送共用这份结构，减少网页与飞书格式分叉。
- 推送报告契约 v2：飞书推送和订阅页历史预览固定使用晨会卡片结构，先展示“晨会摘要、今日只看 3 件事、操作纪律和数据边界”，再展开详细证据层：交易日与市场温度、触发总览、单股市场快照、六组核心骨架、解释与验证链、公告与事件、持仓与操作建议、下一观察点。非日频指标不会消失，缺失项必须明确写为 Missing/Stale。
- 测试推送：订阅卡片可直接生成当前分析报告并发送到飞书，用于核对真实推送内容；不改变正式定时任务或触发规则。
- 飞书卡片化推送：订阅推送默认使用飞书 interactive card 渲染统一报告骨架；可通过 `FEISHU_MESSAGE_MODE=text` 切回纯文本。卡片发送失败时会自动降级为纯文本。
- 持仓与操作建议：订阅推送会读取已上传交易记录生成的持仓基线，结合单票在组合内的估算权重、行情/技术/市场天气/公告/数据质量，输出保守规则建议和下一证据；无持仓基线时只输出研究监控姿态。

## 系统健康检查

后端提供 `GET /api/system/health`，前端提供 `/health` 页面。当前检查：

- 数据库连通性及核心表计数。
- 调度器启用/运行状态、排程和下一次运行时间。
- 当日 A 股交易日历判断及官方/兜底来源说明。
- 关键配置：公告窗口、分析证据窗口、飞书消息模式、CORS。
- 数据源清单：官方来源与二级来源分开标注。
- Stale Sources / Missing Inputs 使用统一结构：指标、最后已知日期、尝试来源、首选来源、判断影响和下一来源。

> PDF 抽取成功时优先展示正文结构化摘要；失败时保留标题/分类规则摘要，并明确写入 `pdf_extract_status` 与失败原因。上交所部分 PDF 直链若返回 JS 验证页，系统会尝试自动计算 `acw_sc__v2` cookie 后重试；仍失败时才标为 `not_pdf_response`，不会伪造正文摘要。

## 数据源策略

默认数据源只作为 MVP 示例：

- 行情：Sina 实时行情接口（二级来源，尽力而为）
- 估值/历史 K 线/技术指标：Eastmoney / Tencent 二级接口，尽力而为；失败时不编造
- 市场天气：Eastmoney A 股列表和行业板块列表用于市场宽度、涨跌停、成交额、行业涨跌和主力净流入；Sina/Yahoo 用于港股、美股和商品上下文；行业 provider v1 会复用这些读数补充行业骨架
- 公告/财报：上交所/深交所官方公告接口；已支持规则化 PDF 正文/表格抽取和部分财报字段解析，完整会计报表解析仍在后续计划中
- 自定义行业数据：可选把 CSV 放入 `data/industry_providers/`，Docker 会挂载到 API 容器 `/data/industry_providers`；默认目录可通过 `INDUSTRY_PROVIDER_DATA_DIR` 修改。
- 网页管理入口：打开首页“显示高级” → “行业数据”，可以管理 `copper_chain.csv` 和 `custom_metrics.csv`，上传前会校验必要列和关键行字段。

### 自定义铜链 CSV

如果你有授权可用的 TC/RC、库存、升贴水等数据，可以复制示例文件：

```bash
cp data/industry_providers/copper_chain.example.csv data/industry_providers/copper_chain.csv
```

支持列：

| 列名 | 说明 |
| --- | --- |
| `metric` | 指标名，当前支持 `tc_rc`、`tc`、`rc`、`lme_inventory`、`shfe_inventory`、`comex_inventory`、`bonded_inventory`、`shfe_spot_premium`、`spot_premium`、`curve_spread`、`import_profit` |
| `as_of` | 数据截止日期或时间 |
| `value` | 数值 |
| `unit` | 单位，例如 `USD/t`、`t`、`CNY/t` |
| `source` | 数据来源名称 |
| `source_url` | 可选来源链接 |
| `note` | 可选口径说明 |

系统会按同一 `metric` 的最新 `as_of` 取值。示例文件不会被读取，只有命名为 `copper_chain.csv` 的文件才会生效。自定义数据会在报告中标为 `CustomProvider copper_chain.csv`，不会伪装成官方来源。

### 通用自定义行业指标 CSV

如果某个行业指标还没有内置 provider，可以复制示例文件：

```bash
cp data/industry_providers/custom_metrics.example.csv data/industry_providers/custom_metrics.csv
```

支持列：

| 列名 | 说明 |
| --- | --- |
| `symbol` | 可选股票代码，例如 `600519.SH`。填写后只匹配该股票。 |
| `industry` | 可选行业名，例如 `白酒`、`保险`、`半导体/电子`。当 `symbol` 为空时按行业匹配。 |
| `metric` | 指标名称，会作为报告中的行业骨架行名。 |
| `status` | `Available` / `Partial` / `Missing`，默认 `Available`。 |
| `as_of` | 数据截止日期或时间。 |
| `value` | 可选数值。 |
| `unit` | 可选单位。 |
| `latest_reading` | 可选完整读数；若为空，系统会用 `metric + value + unit` 生成。 |
| `source` / `source_url` | 数据来源名称和链接。 |
| `relevance` | 为什么这个指标重要。 |
| `next_evidence` | 下一步需要跟踪什么证据。 |
| `note` | 可选口径说明。 |

匹配规则：`symbol` 精确匹配优先；没有 `symbol` 时按 `industry` 匹配；同一 `symbol/industry + metric` 多行时取最新 `as_of`。通用自定义指标会在报告中标为 `CustomProvider custom_metrics.csv`。

后续计划把数据源抽象为 provider：

- OfficialExchangeProvider：上交所/深交所/北交所公告
- AkShareProvider：行情、指数、宏观、行业数据
- TushareProvider：用户自带 token 的可选数据源
- CustomProvider：用户自定义企业内数据源

## 项目文档

- [架构说明](docs/architecture.md)
- [部署说明](docs/deployment.md)
- [备份与恢复](docs/backup.md)
- [第一版发布前 Checklist](docs/MVP_RELEASE_CHECKLIST.md)
- [Public Equity Investing 能力边界](docs/public-equity-investing.md)
- [贡献指南](CONTRIBUTING.md)
- [许可证](LICENSE)

## 路线图

1. MVP 骨架与基础页面
2. 行业指标引擎：白酒、有色、保险、银行、券商、地产、半导体/电子、新能源/电池、家电/消费制造、医药、公用/能源等
3. PDF 表格抽取、财报结构化解析与 Stale/Missing Inputs
4. 飞书卡片消息
5. 多数据源配置与数据质量标注
