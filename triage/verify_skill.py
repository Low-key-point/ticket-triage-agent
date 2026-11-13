"""数据查看器的真实预览核对与故障注入。"""
import json
import pyarrow.parquet as pq
from .data import ROOT, DatasetViewer, SKILL_REVISION, check_source, write_json


def verify():
    originals=pq.read_table(ROOT/"data/raw/zh/minds14-zh.parquet",columns=["transcription", "intent_class"]).to_pylist()
    evidence={"组件":"数据来源检查Skill","版本":SKILL_REVISION,"用途":"来源预览与固定文件交叉核验","训练使用镜像":False,
              "真实预览":check_source(originals)}
    results=[]
    for name,payload in [("缺失字段",b'{"num_rows_total":3}'),("提前空页",b'{"rows":[],"num_rows_total":3}'),("数量类型错误",b'{"rows":[1],"num_rows_total":"3"}'),
                         ("缺失文本标签",b'{"rows":[{"row_idx":0,"row":{}}],"num_rows_total":1}'),
                         ("行号不连续",b'{"rows":[{"row_idx":2,"row":{"transcription":"test","intent_class":0}}],"num_rows_total":1}')]:
        rejected=False
        try: DatasetViewer(lambda u,p=payload:p).query("rows")
        except ValueError: rejected=True
        results.append({"故障":name,"普通JSON解析接受":isinstance(json.loads(payload),dict),"适配器拒绝":rejected})
    evidence["注入故障"]=results
    evidence["限制"]="只证明结构校验能发现指定故障，不代表分类精度提升。"
    write_json(ROOT/"reports/skill_validation.json",evidence)
    print(json.dumps(evidence,ensure_ascii=True))


if __name__=="__main__": verify()
