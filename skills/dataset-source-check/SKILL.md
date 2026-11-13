---
name: dataset-source-check
description: 在工单分类数据准备阶段预览公开数据，与固定文件交叉核验并保存来源检查记录。
license: Apache-2.0
---

# 数据来源检查

此 Skill 改编自 Hugging Face Dataset Viewer Skill 的只读来源确认、分页预览和结构检查工作流；工具适配器由本项目编写。它在数据准备阶段执行，不参与客户工单的最终分类。

## 来源与版本

- 上游：[huggingface-datasets/SKILL.md](https://github.com/huggingface/skills/blob/25910b3d0ba31a2ba102f901cdc9e008c278a69c/skills/huggingface-datasets/SKILL.md)
- 上游提交：`25910b3d0ba31a2ba102f901cdc9e008c278a69c`
- 上游作者：Hugging Face；许可：Apache License 2.0，全文见根目录 LICENSES.md。
- 本地适配版本：1.0；实现：`triage/data.py`，行为核验：`triage/verify_skill.py`。

## 执行步骤

1. 运行 `python -m triage.data`。下载 MInDS-14 的固定修订 Parquet，先检查 SHA256 和502条记录数，失败立即停止。
2. 调用 DatasetViewer 的只读 `rows` 工具。数据集固定为 PolyAI/minds14，配置 zh-CN、划分 train；只取前100条预览。
3. 检查对象、分页总数、连续行号、文本类型和0至13整数标签。仅接受合法响应。
4. 将预览的“转写、标签”组合与固定文件作多重集合比较，记录匹配数和总数。
5. 在线预览匹配、不同或不可用分别记录；训练始终使用已校验的固定文件。服务异常不能替换数据或让生成数据混入训练源。
6. 输出 `reports/source_validation.json`，再执行清洗和分组划分。日志不记录客户工单或凭据。
7. 运行 `python -m triage.verify_skill`，保存真实来源比对和5类故障注入结果至 `reports/skill_validation.json`。

## 输入和输出

- 输入：已验哈希的本地原始记录；工具参数 endpoint、offset、length。端点仅 rows/splits，offset为非负整数，length为1至100整数。
- rows 输出：JSON对象，含 rows 列表、num_rows_total 非负整数；每行含连续 row_idx 及 row.transcription、row.intent_class。
- Skill 输出：来源修订、文件哈希、上游版本、状态 matched/different/unavailable、预览/匹配数量、训练来源和处理决定。
- 失败输出：校验异常被拒绝并标记 unavailable；本地文件哈希不一致直接终止数据准备。

## 权限、服务和限制

只需要读取本地原始文件、写入本地 reports 以及向 Hugging Face 官方数据服务发起 HTTPS GET。公开数据不需要令牌，不接受任意URL、不执行远程脚本、不上传工单、不访问私有数据。请求超时35秒，网络错误最多重试2次。

在线查看器没有在本工具中固定修订号，因此预览可能随上游变化；固定文件及其SHA256才是训练依据。100条预览和字段验证不能证明数据标注正确，也不能证明分类精度提高。

## 适配与行为核验

上游通用查看器支持搜索、筛选、上传和多种数据集。本项目只复用其只读探索流程，将来源固定并收窄工具范围，补充标签/行号校验、固定文件比对、故障回退和本地记录。测试覆盖5种错误响应、预览内容漂移和网络失败；在相同故障输入下比较普通JSON解析与适配器拒绝行为。运行命令已经纳入 scripts/reproduce.ps1。
