"""固定中文数据来源、完整性校验与相似文本分组隔离。"""
from __future__ import annotations
import hashlib
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REVISION = "40ce77cb32a384e4d50a568e1ec39ac804019d33"
SKILL_REVISION = "25910b3d0ba31a2ba102f901cdc9e008c278a69c"
SOURCE_URL = f"https://huggingface.co/datasets/PolyAI/minds14/resolve/{REVISION}/zh-CN/train-00000-of-00001.parquet"
SOURCE_SHA256 = "cea0246e1a54afe5a3ab9d9542baa53c7cb45fc8f4e28e7872ebafefb25ba99d"


def write_json(path, value):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding="utf-8")


def get_bytes(url, retries=2):
    for attempt in range(retries+1):
        try:
            req=urllib.request.Request(url,headers={"User-Agent":"chinese-triage-course/2.0"})
            with urllib.request.urlopen(req,timeout=35) as response:
                return response.read()
        except OSError:
            if attempt==retries: raise
            time.sleep(.3*(attempt+1))


class DatasetViewer:
    """只读数据查看器；数据集、语言和划分固定为中文子集。"""
    def __init__(self, fetch=None):
        self.fetch=fetch or get_bytes

    def query(self, endpoint, **params):
        if endpoint not in {"rows","splits"}:
            raise ValueError("仅允许只读预览")
        query={"dataset":"PolyAI/minds14"}
        if endpoint=="rows":
            config=params.get("config","zh-CN")
            split=params.get("split","train")
            offset=params.get("offset",0)
            length=params.get("length",100)
            if config!="zh-CN" or split!="train" or type(offset)!=int or offset<0 or type(length)!=int or not 1<=length<=100:
                raise ValueError("中文预览参数不合法")
            query.update(config=config,split=split,offset=offset,length=length)
        value=json.loads(self.fetch("https://datasets-server.huggingface.co/"+endpoint+"?"+urllib.parse.urlencode(query)))
        if not isinstance(value,dict): raise ValueError("响应必须为对象")
        if endpoint=="rows":
            rows=value.get("rows"); total=value.get("num_rows_total")
            if not isinstance(rows,list) or type(total)!=int or total<0:
                raise ValueError("分页字段不合法")
            if len(rows)>length or len(rows)!=min(length,max(0,total-offset)):
                raise ValueError("分页数量不完整")
        elif not isinstance(value.get("splits"),list):
            raise ValueError("划分字段不合法")
        return value


def prepare():
    import numpy as np
    import pyarrow.parquet as pq
    from sklearn.feature_extraction.text import HashingVectorizer
    from sklearn.model_selection import StratifiedGroupKFold
    from scipy.sparse.csgraph import connected_components
    from .knowledge import LABELS
    from .policy import sanitize_texts
    raw=ROOT/"data/raw/zh/minds14-zh.parquet"
    raw.parent.mkdir(parents=True,exist_ok=True)
    if not raw.exists(): raw.write_bytes(get_bytes(SOURCE_URL))
    if hashlib.sha256(raw.read_bytes()).hexdigest()!=SOURCE_SHA256:
        raise ValueError("中文原始数据完整性校验失败")
    table=pq.read_table(raw,columns=["transcription","intent_class","path"])
    original=table.to_pylist()
    if len(original)!=502: raise ValueError("中文数据数量与固定版本不符")
    rows=[]; seen={}; duplicate_count=0; non_chinese_count=0
    for i,row in enumerate(original):
        text=row["transcription"]
        label=row["intent_class"]
        if not isinstance(text,str) or not text.strip() or type(label)!=int or label not in range(14):
            raise ValueError("中文数据包含非法文本或标签")
        if not re.search(r"[\u3400-\u9fff]",text):
            non_chinese_count+=1
            continue
        normalized=sanitize_texts([text])[0]
        key=re.sub(r"[^\u3400-\u9fffa-z0-9]","",normalized)
        if key in seen:
            if seen[key]!=label: raise ValueError("相同中文文本有冲突标签")
            duplicate_count+=1
            continue
        seen[key]=label
        rows.append({"id":f"中文-{i:04d}","text":text,"label":LABELS[label],"source_path":row["path"]})
    x=HashingVectorizer(analyzer="char",ngram_range=(2,4),n_features=2**18,alternate_sign=False,norm="l2").transform(sanitize_texts([r["text"] for r in rows]))
    similarities=x@x.T
    graph=similarities>=.90
    _,groups=connected_components(graph,directed=False)
    y=np.array([r["label"] for r in rows]); ids=np.arange(len(rows))
    trainval,test=next(StratifiedGroupKFold(5,shuffle=True,random_state=42).split(ids,y,groups))
    remaining,validation=next(StratifiedGroupKFold(5,shuffle=True,random_state=43).split(trainval,y[trainval],groups[trainval]))
    validation=trainval[validation]; remaining=trainval[remaining]
    train,calibration=next(StratifiedGroupKFold(5,shuffle=True,random_state=44).split(remaining,y[remaining],groups[remaining]))
    train=remaining[train]; calibration=remaining[calibration]
    parts={"train":train,"calibration":calibration,"validation":validation,"test":test}
    sets=[set(groups[idx]) for idx in parts.values()]
    assert all(not a&b for i,a in enumerate(sets) for b in sets[i+1:])
    data={name:[{**rows[int(i)],"group":int(groups[i])} for i in indices] for name,indices in parts.items()}
    if any(set(r["label"] for r in part)!=set(LABELS) for part in data.values()):
        raise ValueError("某个划分未覆盖全部中文类别")
    write_json(ROOT/"data/processed/zh_splits.json",data)
    split_hash=hashlib.sha256((ROOT/"data/processed/zh_splits.json").read_bytes()).hexdigest()
    manifest={"数据集":"MInDS-14中文子集","语言":"zh-CN","原始条数":502,"精确重复移除":duplicate_count,"非中文移除":non_chinese_count,
              "保留条数":len(rows),"类别数":14,"相似阈值":.90,"相似连边数":int((graph.nnz-len(rows))/2),
              "划分数量":{k:len(v) for k,v in data.items()},"来源版本":REVISION,"来源SHA256":SOURCE_SHA256,
              "划分SHA256":split_hash,"说明":"使用中文语音转写及原意图标签，不使用音频或英文转写。无官方测试划分；固定种子分组隔离后的自建测试集。"}
    write_json(ROOT/"reports/data_manifest.json",manifest)
    write_json(ROOT/"reports/split_ids.json",{k:[r["id"] for r in v] for k,v in data.items()})
    print(json.dumps(manifest,ensure_ascii=True))
    return data


def load_splits():
    manifest=json.loads((ROOT/"reports/data_manifest.json").read_text(encoding="utf-8"))
    raw=(ROOT/"data/processed/zh_splits.json").read_bytes()
    if hashlib.sha256(raw).hexdigest()!=manifest["划分SHA256"]:
        raise ValueError("数据划分完整性校验失败")
    return json.loads(raw)


if __name__=="__main__": prepare()
