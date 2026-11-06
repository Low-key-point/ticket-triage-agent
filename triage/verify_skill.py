"""中文数据查看器的真实预览核对与故障注入。"""
import json
import pyarrow.parquet as pq
from .data import ROOT, DatasetViewer, SKILL_REVISION, write_json


def verify():
    originals=pq.read_table(ROOT/"data/raw/zh/minds14-zh.parquet",columns=["transcription"]).column(0).to_pylist()
    evidence={"组件":"公开数据集只读查看器","版本":SKILL_REVISION,"用途":"中文数据预览与分页校验","训练使用镜像":False}
    try:
        page=DatasetViewer().query("rows",length=100)
        texts=[r["row"]["transcription"] for r in page["rows"]]
        evidence["真实预览"]={"可用":True,"总条数":page["num_rows_total"],"预览条数":len(texts),"与原始文本匹配":sum(t in originals for t in texts),"仅预览核验":True}
    except (ValueError,OSError,KeyError) as exc:
        evidence["真实预览"]={"可用":False,"错误类型":type(exc).__name__,"回退":"固定版本原始文件"}
    results=[]
    for name,payload in [("缺失字段",b'{"num_rows_total":3}'),("提前空页",b'{"rows":[],"num_rows_total":3}'),("数量类型错误",b'{"rows":[1],"num_rows_total":"3"}')]:
        rejected=False
        try: DatasetViewer(lambda u,p=payload:p).query("rows")
        except ValueError: rejected=True
        results.append({"故障":name,"普通JSON解析接受":isinstance(json.loads(payload),dict),"适配器拒绝":rejected})
    evidence["注入故障"]=results
    evidence["限制"]="只证明结构校验能发现指定故障，不代表分类精度提升。"
    write_json(ROOT/"reports/skill_validation.json",evidence)
    print(json.dumps(evidence,ensure_ascii=True))


if __name__=="__main__": verify()
