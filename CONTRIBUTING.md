# Contributing

欢迎贡献 `astock-watchtower`。这个项目的目标不是做一个“万能荐股器”，而是做一个自托管、可解释、会标注数据质量的 A 股订阅与分析工具。

## 开发原则

- 不编造数据：缺失字段必须标记为 Missing Inputs 或 Stale Sources。
- 官方优先：公告、财报、交易日历优先使用交易所/公司/监管机构来源。
- 二级来源要标注：行情、估值、K 线等二级来源必须明确来源和时间。
- 不自动交易：所有“操作建议”只能是研究提醒，不连接券商下单。
- 规则先于大模型：涉及投资结论的核心触发逻辑优先可解释、可测试；AI 适合作为摘要和解释增强层。

## 本地验证

后端：

```bash
PYTHONPYCACHEPREFIX=/tmp/astock_pycache PYTHONPATH=apps/api apps/api/.venv/bin/python -m compileall apps/api/app
cd apps/api
.venv/bin/python -m pytest
```

前端：

```bash
cd apps/web
npm run build
```

部署后 smoke test：

```bash
python3 scripts/smoke_test.py
```

## 数据源贡献

新增 provider 时请同时说明：

- 来源类型：official / secondary / user-provided。
- 时间戳语义：实时、延迟、收盘后、报告期。
- 失败行为：不可得时返回 Missing/Stale，不要 fallback 成无来源估计值。
- 授权注意事项：是否需要 token、是否限制商用或再分发。

## 行业指标贡献

新增行业指标时建议分三层：

- 核心骨架：影响价值创造、现金流、资本或风险的主指标。
- 解释层：帮助解释短期价格/估值/基本面变化的上下文。
- 验证层：用来确认或反驳核心信号的交叉证据。
