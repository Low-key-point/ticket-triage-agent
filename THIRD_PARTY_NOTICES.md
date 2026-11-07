# 数据与组件来源、许可和修改

| 组件 | 版本或提交 | 许可 | 用途和修改 |
| --- | --- | --- | --- |
| MInDS-14中文数据 | 40ce77cb32a384e4d50a568e1ec39ac804019d33 | CC BY 4.0 | 仅中文转写；去除无汉字文本、精确重复并分组划分 |
| 公开数据集查看器工具说明 | 25910b3d0ba31a2ba102f901cdc9e008c278a69c | Apache 2.0 | 只读中文预览；增加白名单、字段和分页校验 |
| scikit-learn | 1.7.2 | BSD 3-Clause | 特征、分类、校准、交叉验证及指标 |
| NumPy / SciPy | 2.2.6 / 1.16.3 | BSD及发行包所列依赖许可 | 数组、稀疏矩阵和统计 |
| Apache Arrow | 19.0.1 | Apache 2.0 | 读取固定数据文件的指定列 |
| Flask | 3.1.2 | BSD 3-Clause | 本地网页接口 |
| joblib | 1.5.2 | BSD 3-Clause | 可信模型保存与加载 |
| pytest | 8.4.2 | MIT | 自动化测试 |

## 可核查来源

- 中文数据页面：https://huggingface.co/datasets/PolyAI/minds14
- 数据集中文子集文件：https://huggingface.co/datasets/PolyAI/minds14/tree/40ce77cb32a384e4d50a568e1ec39ac804019d33/zh-CN
- 工具说明：https://github.com/huggingface/skills/tree/25910b3d0ba31a2ba102f901cdc9e008c278a69c
- 机器学习库：https://scikit-learn.org/
- 数组计算：https://numpy.org/
- 科学计算：https://scipy.org/
- 数据文件读取：https://arrow.apache.org/
- 网页框架：https://flask.palletsprojects.com/
- 模型存储：https://joblib.readthedocs.io/
- 测试框架：https://docs.pytest.org/

数据发布方为PolyAI团队；数据是带意图标签的中文语音转写，含口语和识别噪声，不是本项目采集的客户记录。保留原始数据归属，不将清洗后数据称为自行采集。

项目自编部分包括中文清洗规则、划分核验、状态机、知识与队列、界面、复核和实验整合。OpenAI Codex协助设计、编码、调试、实验和文档制作；不声称全部手工原创。

第三方许可原文位于 third_party/，依赖包自身的完整许可随发行包保留。中文报告使用中文参考资料说明，产品名称与许可证编号保持真实名称以便核查。本项目使用DeepSeek付费API作为可选辅助功能，由用户自行配置；服务条款与生成内容使用条件以DeepSeek官方平台为准。新增数据候选只做来源核查，未并入训练或再分发。

- DeepSeek结构化输出说明：https://api-docs.deepseek.com/zh-cn/guides/json_mode
- DeepSeek模型与计费说明：https://api-docs.deepseek.com/zh-cn/quick_start/pricing
- 数据候选核查见 docs/数据集候选核查.md。
