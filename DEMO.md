# 银行客服工单分流智能体演示指南

本项目是一个可本地运行的 Agent 原型。系统先用本地机器学习模型判断工单业务类别，再由规则与概率门槛决定自动分流或转入人工复核；DeepSeek 只负责按需生成复核摘要、批量模拟工单和训练候选样本。分类和队列映射不依赖大模型，因此没有 API 密钥也能演示核心流程。

## 先看什么

| 材料 | 说明 |
| --- | --- |
| [工单分流结果](demo/工单分流.png) | 候选类别、置信度、知识说明、执行轨迹和最终队列 |
| [复核工作台](demo/复核工作台.png) | 低置信、范围内异常和范围外工单的人工处理 |
| [复核完成](demo/复核完成.png) | 最终类别、队列、理由和原始建议的追溯记录 |
| [系统架构](demo/architecture.png) | 页面、Agent、模型、工具、数据与存储的关系 |
| [Agent 工作流](demo/workflow.png) | 自动分流、转人工和持久化的状态路径 |
| [模型对比](demo/model-comparison.png) | 基线、未校准模型与最终校准模型的宏平均 F1 |
| [分流策略对比](demo/routing-comparison.png) | 自动覆盖率与自动队列精确率之间的取舍 |
| [DeepSeek 功能验收](demo/AI_ACCEPTANCE_20261121.md) | 实际连接、摘要生成、模拟工单生成与训练隔离结果 |
| [测试矩阵](TEST_MATRIX.md) | 功能、断言和证据的对应关系 |

## 5 分钟本地演示

环境要求：Python 3.12、PowerShell。以下命令在项目根目录执行。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m triage.data
.\.venv\Scripts\python.exe -m triage.train
.\.venv\Scripts\python.exe -m triage.web
```

浏览器打开 `http://127.0.0.1:8765/`，按以下顺序操作：

1. 在“处理工单”输入“我想查询一下银行账户的余额”。系统应自动识别“查询余额”，生成候选概率、处理说明和轨迹，并进入对应队列。
2. 输入“请推荐一只值得购买的股票”。系统应因业务范围外转入复核；在“复核工作台”选择“其他”、填写理由并确认后，记录进入“其他工单队列”。
3. 下载 [批量示例 CSV](demo/tickets.csv)，在批量处理区域导入。完成后可导出包含最终分类、队列和状态的本地记录。
4. 打开“实验结果”，查看固定测试集上的分类、分流、消融和失败案例指标。

数据和模型准备命令会重新生成 `data/`、`models/` 和 `reports/`。这些运行产物不进入 Git；仓库提供固定数据来源、校验逻辑、训练参数和复现脚本。

## DeepSeek 演示

DeepSeek 是可选工具。进入“大模型设置”，在本机页面填写自己的 API 密钥，保存后先执行“测试实际连接”。

- 在工单详情生成复核摘要。输入会先脱敏，输出必须包含核心诉求、原文依据、待补充信息和复核建议。格式错误或原文依据不存在时，原工单状态保持不变。
- 在“数据增强与模拟”选择类别与数量，生成训练候选或模拟工单。训练候选必须通过去重、测试集污染、个人信息和人工审核检查；模拟工单永远不参与训练。
- 候选训练使用已审核样本，沿用原校准集和验证集，独立保存模型并与基础模型比较。候选模型不会自动替换线上模型。

密钥只保存在服务端进程内存中，8 小时后或服务重启时失效；密钥不会写入工单数据库、日志或浏览器持久存储。

## API 快速检查

服务启动后，可用 PowerShell 验证核心接口：

```powershell
Invoke-RestMethod http://127.0.0.1:8765/api/health
Invoke-RestMethod http://127.0.0.1:8765/api/labels
Invoke-RestMethod http://127.0.0.1:8765/api/tickets -Method Post -ContentType 'application/json' -Body '{"text":"我想查询账户余额"}'
Invoke-RestMethod http://127.0.0.1:8765/api/tickets
Invoke-WebRequest http://127.0.0.1:8765/api/export -OutFile tickets.csv
```

接口仅接受本机访问；写操作会拒绝跨来源请求。上传内容上限为 2 MB，单次批量处理最多 500 条。

## 一键复现

```powershell
.\scripts\reproduce.ps1
```

该脚本依次准备固定数据、检查来源、训练、评估、复现增强实验和运行测试。只复验已保存的合成样本时不调用付费接口。

单独执行测试：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

当前测试集包含 129 个自动化用例，覆盖 60 个分类与分流边界、状态持久化、人工复核权限、CSV 导入导出、所有公开路由、页面资源契约、本机访问与跨站防护、2 MB 限制、密钥隔离与过期、DeepSeek 异常响应、摘要回滚、数据污染隔离、候选训练和项目复现文件。逐项对应见 [TEST_MATRIX.md](TEST_MATRIX.md)。

## 已知边界

固定测试集规模为 95 条，适用于课程原型和工程闭环验证，不能直接代表真实银行生产流量。系统不办理真实账户操作，也不把模型输出当作银行政策。生产部署还需要经授权的历史工单、持续标注、漂移监控、权限审计和服务等级验证。
