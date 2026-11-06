# 分流台 银行客服工单 Agent

一个可在本机运行的机器学习课程原型：英文咨询 → 77类意图分类 → 演示业务队列与处理说明 → 自动分流或人工复核。中文网页展示候选概率、线性特征贡献、状态轨迹、复核记录和实验结果。

本项目不执行真实金融操作，不依赖付费大模型 API。报告、演示截图和个人提交材料保存在项目负责人的本地目录，不上传 GitHub。

## 已实现

- 固定 BANKING77 版本与 SHA-256，近重复分组，训练、校准、验证和官方测试隔离。
- 多数类、关键词、朴素贝叶斯、逻辑回归、线性 SVM，3折分组交叉验证，独立 sigmoid 概率校准。
- 77类显式队列映射、演示知识查询、保守复核策略、SQLite 持久化、幂等提交和人工修正。
- CSV 批量导入、逐行错误、安全导出，中文网页与命令行入口。
- 官方3080条测试、120条构造边界用例、60条模拟工作流、200次单请求耗时；完整原始结果通过评估脚本在本地生成。
- 开源 skill 只读适配与行为核验，详见 [组件来源](THIRD_PARTY_NOTICES.md)。

## 安装

推荐 Python 3.12，支持 Python 3.11及以上。联网用于安装和首次数据准备，模型训练与演示可在准备完成后离线执行。Windows PowerShell：

```powershell
git clone https://github.com/Low-key-point/ticket-triage-agent.git
cd ticket-triage-agent
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
```

Linux/macOS 使用 `.venv/bin/python` 替换下列 Windows Python 路径。所有命令从仓库根目录运行。

## 数据 训练与评估

```powershell
.\.venv\Scripts\python.exe -m triage.data
.\.venv\Scripts\python.exe -m triage.train
.\.venv\Scripts\python.exe -m triage.verify_skill
.\.venv\Scripts\python.exe -m triage.evaluate
.\.venv\Scripts\python.exe -m pytest -q
```

也可运行 `powershell -File scripts/reproduce.ps1` 顺序执行以上步骤。首次数据准备包括近重复检测，比推理慢。网络失败时会有限重试；远端镜像检查失败不替换训练数据来源。清理只发生在生成的训练划分内，原始文件保持不变。校验和不一致会停止准备或训练，不静默覆盖未知数据。

训练生成 `models/model.joblib`，评估生成 `reports/` 下的指标、逐样本预测、混淆矩阵、失败样例、阈值搜索和时间记录；这些本地生成物不纳入 Git。网页实验页在运行评估后展示真实结果。不同机器时间指标可能不同，CPU和依赖信息写入评估输出。

## 启动

```powershell
.\.venv\Scripts\python.exe -m triage.web
```

打开 **http://127.0.0.1:8765**。页面有“处理工单”“复核工作台”“实验结果”。仅绑定本机地址，无多用户登录；Flask 内置服务器用于本地演示。需要公网部署时须另行设计鉴权和生产服务器。

命令行示例：

```powershell
.\.venv\Scripts\python.exe -m triage.cli "When will my new card arrive?" --id demo-001
```

CSV 示例见 `examples/tickets.csv`，其中故意含一条空文本以演示逐行错误。重复编号及不同内容会报告冲突。复核理由会脱敏；数据库仅存脱敏预览与内容哈希。只使用公开或虚构文本。

## 验收与证据边界

原需求目标包括宏平均 F1 ≥ 0.80、自动分流队列正确率 ≥ 0.95且覆盖率 ≥ 0.50；以每次评估产生的真实结果判定，不在代码中伪造通过。队列正确率与77类严格意图正确率分别报告。

人工复核界面由脚本和浏览器操作验证。60条模拟任务中，以真值驱动复核后的完成率仅说明流程能闭环，不代表真实人工正确率或全部自动完成。120条边界样例是 AI 辅助构造的回归用例，不足以证明覆盖所有未知输入。未开展用户访谈和人工耗时实验，也不声称节省人工时间。

置信度经过校准仍可能失准；非英文检测和域外识别基于启发式，拉丁字母的其他语言、复杂多意图及陌生银行文本仍可能误分。低概率门槛由验证集选择，须结合覆盖率、错分数、校准误差和失败样例解读。

## 目录

| 路径 | 用途 |
| --- | --- |
| `triage/data.py` | 固定数据下载、哈希、分组划分与 skill 适配 |
| `triage/train.py` | 交叉验证、模型训练、校准、阈值冻结 |
| `triage/agent.py` | 分类解释、工具调用、持久化、复核与批处理 |
| `triage/policy.py`、`triage/knowledge.py` | 输入政策、脱敏、显式映射与知识条目 |
| `triage/web.py`、`web/` | 中文本地界面与接口 |
| `triage/evaluate.py` | 测试、消融、错误与性能输出 |
| `tests/` | 边界、接口、存储、来源与回归测试 |
| `config/` | 预先列出的实验网格与标签 |
| `docs/` | [需求分析](docs/需求分析.md)、[构建步骤](docs/构建步骤.md)、[范围调整](docs/范围调整.md) |

不要加载来历不明的 joblib/pickle 模型。仓库不包含密钥、真实客户数据、原课程 Word 文件或学生身份信息。

## 归属与 AI 辅助

BANKING77 采用 CC BY 4.0，Hugging Face skill 采用 Apache 2.0。完整来源、版本和修改说明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。项目使用 OpenAI Codex 辅助方案设计、编码、调试、自动化测试和文档编写；提交者需理解设计、核验结果并遵守课程要求。
