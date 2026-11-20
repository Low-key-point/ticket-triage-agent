# 测试与证据矩阵

测试入口为 `python -m pytest -q`。当前共有 129 个自动化用例；下表按功能归类，不把所有参数组合重复列为独立功能。

| 功能 | 自动化检查 | 主要证据 |
| --- | --- | --- |
| 数据准备与来源 | 数据集结构、配置约束、固定文件校验、来源一致／漂移／不可用、SHA256 失败即停止 | `test_source_skill.py`、`test_agent.py`、`reports/source_validation.json` |
| 分类与分流边界 | 60 个正常、低置信、范围外、异常、工具失败和模型失败场景 | `tests/cases.py`、`reports/boundary_results.json` |
| 工单状态机 | 幂等提交、编号冲突、复核持久化、非法复核不修改状态、自动工单禁止绕过复核 | `test_idempotence_and_conflict`、`test_review_state_persistence`、`test_bad_review_no_mutation` |
| “其他”权限 | 模型不能直接输出“其他”，该类别只在复核工作台由人工确认 | `test_predictor_cannot_route_other`、`test_other_is_manual_only` |
| 数据暴露边界 | 手机号、卡号、邮箱脱敏；摘要只接收脱敏文本，数据库与响应不保存测试密钥 | `test_chinese_redaction`、`test_summary_sends_redacted_only` |
| DeepSeek 契约 | 固定端点、JSON 模式、模型与超时参数、禁止重定向、错误码与超时不泄漏密钥 | `test_deepseek_contract_and_no_redirect`、`test_provider_error_does_not_leak` |
| 摘要可靠性 | 输出约束、原文依据校验、失败不覆盖旧摘要、缺失工单不调用提供方 | `test_summary_persistence_and_fallback`、`test_summary_requires_an_existing_ticket` |
| 密钥生命周期 | 会话隔离、清除、8 小时过期、64 会话上限 | `test_config_session_isolation_and_clear`、`test_llm_credentials_expire_after_eight_hours` |
| 生成与审核 | 参数校验、异步状态、逐条批准、模拟样本禁止训练、下载记录 | `test_generation_api_end_to_end`、`test_generation_parameter_validation` |
| 污染与隐私隔离 | 测试集重复样本被过滤、PII 被拒、校准／验证／测试文本不进入生成提示 | `test_duplicate_test_contamination_and_pii`、`test_generation_isolation_review_and_simulation` |
| 候选模型实验 | 基础模型和划分不变、候选独立保存、测试集不参与选择、激活需显式确认 | `test_candidate_training_preserves_baseline_and_splits` |
| HTTP 路由 | 19 个公开路由规则及其允许方法逐项核对，包括页面静态资源规则 | `test_route_contract_covers_every_public_entry` |
| 页面与静态资源 | 首页、CSS、JS 可访问；脚本引用的 DOM 节点存在；本机仓库链接有效 | `test_static_assets_and_security_headers`、`test_frontend_dom_contract_matches_scripts` |
| 批量和导出 | 本地创建、状态筛选、CSV 上传、错误上传、CSV 导出与附件头 | `test_csv_batch_and_export_http_contract`、`test_batch_and_export` |
| HTTP 安全边界 | 拒绝公网主机、跨来源与跨站写请求；安全响应头；2 MB 上限 | `test_remote_host_and_cross_site_mutations_are_rejected`、`test_payload_limit_and_invalid_json` |
| 失败响应 | 404、405、无效批次、数据库异常与工具异常有明确返回 | `test_missing_resources_and_unsupported_methods`、60 个边界用例 |
| 度量接口 | 正式报告存在时返回模型结果；文件不存在时返回 `not_evaluated` | `test_read_and_local_workflow_endpoints`、`test_metrics_fallback_when_report_is_absent` |
| 可复现材料 | README、演示指南、启动／复现脚本、固定依赖、演示图片和 CSV 均存在 | `test_project_contract_files_and_pinned_dependencies` |
| CLI | 命令行帮助可启动且描述输入用途 | `test_cli_help_is_available` |

## 连续集成

`.github/workflows/quality.yml` 在 Windows 上重新准备数据、核验来源、训练、评估、复放增强样本并执行全部测试。运行记录和 `reports/` 会作为构建产物保留，便于检查模型版本、指标和测试结果。

## 测试不替代的验证

自动化用例使用显式 DeepSeek 替身验证契约、回滚和错误处理；真实网络测试由本机页面中的“测试实际连接”完成，需要用户自己的 API 密钥。95 条固定测试集只用于课程项目比较，不能替代真实银行工单的人工作业抽检和长期漂移评估。
