# 第三方来源与改动说明

本项目是课程演示原型。项目代码与界面由项目开发过程编写，使用 AI 辅助设计、编码、调试和文档整理；不把复用组件或生成式辅助隐瞒为手工原创。

| 名称 | 固定版本或提交 | 许可 | 实际用途 |
| --- | --- | --- | --- |
| BANKING77 / PolyAI | 57ec275d8078af65b7731c2a98be812d844a6d6b | CC BY 4.0 | 英文意图分类训练与官方测试 |
| huggingface-datasets skill / Hugging Face | 25910b3d0ba31a2ba102f901cdc9e008c278a69c | Apache 2.0 | 数据镜像探查和分页、结构核验方法 |
| scikit-learn | 1.7.2 | BSD 3-Clause | TF-IDF、模型、校准、交叉验证及指标 |
| NumPy | 2.2.6 | BSD 3-Clause | 数组与统计 |
| SciPy | 1.16.3 | BSD 3-Clause | 稀疏特征与计算 |
| Flask | 3.1.2 | BSD 3-Clause | 本地网页与API |
| joblib | 1.5.2 | BSD 3-Clause | 可信本地模型持久化 |
| pytest | 8.4.2 | MIT | 自动化验收 |

直接与传递依赖版本见 `requirements-lock.txt`；各发行包内含许可证。原始数据不随 Git 仓库重复分发；下载脚本固定提交和已核验哈希。数据准备删除与测试集高度相似的训练侧记录并对训练侧精确重复去重，官方测试集保持不变；这些修改在本地生成的 `reports/data_manifest.json` 中记录。

源自开源 skill 的说明副本位于 `third_party/huggingface-datasets-SKILL.md`，对应 Apache 2.0 全文同目录。该文件作为来源资料而非自动执行入口。适配代码 `triage/data.py` 只实施白名单公开数据查询、分页和错误校验，不实现说明中的上传或会话记录访问。`triage/verify_skill.py` 记录真实接口探查和注入故障对照。

许可副本：`third_party/BANKING77-LICENSE.txt` 和 `third_party/huggingface-skills-LICENSE.txt`。依赖许可证在安装后可由 `importlib.metadata` 查询对应 distribution 的 `.dist-info/licenses`。

## 来源

- PolyAI 数据：https://github.com/PolyAI-LDN/task-specific-datasets
- 数据论文：Casanueva et al. Efficient Intent Detection with Dual Sentence Encoders. 2020. https://arxiv.org/abs/2003.04807
- Hugging Face skills：https://github.com/huggingface/skills
- scikit-learn：https://scikit-learn.org/
- NumPy：https://numpy.org/
- SciPy：https://scipy.org/
- Flask：https://flask.palletsprojects.com/
- joblib：https://joblib.readthedocs.io/
- pytest：https://docs.pytest.org/

队列和知识条目是自编演示规则，不是银行公开政策或真实组织架构。训练模型只支持当前英文任务，不代表生产银行服务。
