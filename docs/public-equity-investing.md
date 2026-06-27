# Public Equity Investing 能力边界与 astock-watchtower 对齐

`astock-watchtower` 是自托管开源项目，运行时不依赖 Codex 的 Public Equity Investing 插件。Public Equity Investing 在本项目中的作用是设计参照：帮助定义 A 股订阅、手动分析、持仓建议、Stale Sources、Missing Inputs 和报告结构的契约。

## 已对齐的能力

- 订阅与手动分析分离：订阅页服务固定订阅池；分析页可临时查询任意 A 股。
- 交易日优先：定时推送先判断 A 股交易日，避免非交易日 routine 噪音。
- 官方优先：公告、财报 PDF 和事件层优先来自上交所/深交所官方公告。
- 行业分层：通用指标 + 行业专属骨架 + 解释/验证层 + Missing Inputs。
- 持仓感知：订阅推送读取本地交易记录形成持仓基线，再输出规则化操作姿态。
- 数据质量显式化：不可得、过期、不可比的数据进入 Stale Sources 或 Missing Inputs，不用替代值伪造结论。

## 不作为运行时依赖的能力

- 不调用 Codex 插件内的远程数据源或私有上下文作为生产数据源。
- 不要求用户安装或登录 Public Equity Investing 才能运行网站。
- 不把插件保存的 watchlist、持仓或自动化状态自动同步到本地数据库；用户需要通过网页或 Excel 导入维护。
- 不把插件输出当作官方行情、估值、公告或财报来源。

## 当前本地实现的对应关系

| Public Equity Investing 需求 | astock-watchtower 实现 |
| --- | --- |
| watchlist / 订阅池 | `/api/subscriptions` + 订阅页 |
| 手动试运行任意 A 股 | `/api/analyze` + 分析页 |
| 交易日判断 | SSE/SZSE 官方休市安排 provider + 本地兜底 |
| 官方公告优先 | SSE/SZSE 公告同步、PDF 正文/表格抽取 |
| 行业特有指标 | `sector_indicator_template` + `sector_mapping` |
| Missing Inputs / Stale Sources | 统一 `data_quality.py` 结构 |
| 持仓与操作建议 | 本地交易记录 + `action_advice.py` 规则引擎 |
| 飞书推送 | 自托管 webhook / card / text fallback |

## 后续可选增强

如果未来要让项目更接近专业 Public Equity Investing 工作流，建议优先做成“用户自带数据源”的 provider，而不是绑定 Codex 插件：

1. Tushare / AkShare / Wind-like CSV provider：行情、指数、资金流、行业指数。
2. 用户上传研究资料 provider：内部 Excel、PDF、纪要和行业数据。
3. 行业插件式指标包：不同目录维护行业模板、字段抽取规则、验证链和阈值。
4. AI 摘要 provider：用户自配 OpenAI API key 后，对公告正文和财报表格生成可审计摘要；默认关闭。

这样开源项目可以独立运行，Public Equity Investing 继续作为高质量研究工作流的参照，而不是隐藏依赖。
