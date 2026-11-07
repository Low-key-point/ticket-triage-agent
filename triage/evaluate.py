"""冻结测试集上的模型、工作流、边界与性能评估。"""
import csv
import json
import platform
import tempfile
import time
from collections import Counter
from pathlib import Path
import numpy as np
from sklearn.metrics import accuracy_score, f1_score, classification_report, confusion_matrix
from .agent import Agent, Store, Predictor
from .data import ROOT, load_splits, write_json
from .knowledge import MAPPING, LABELS
from .policy import input_reasons, decide
from .web import create_app


def score(y,p):
    return {"accuracy":float(accuracy_score(y,p)),"macro_f1":float(f1_score(y,p,labels=LABELS,average="macro",zero_division=0))}


def selection_metrics(y,p,mask):
    n=sum(mask); q=sum(MAPPING[a]==MAPPING[b] for a,b,on in zip(y,p,mask) if on)
    k=sum(a==b for a,b,on in zip(y,p,mask) if on)
    if n:
        ph=q/n; z=1.96; d=1+z*z/n; center=(ph+z*z/(2*n))/d; half=z*((ph*(1-ph)/n+z*z/(4*n*n))**.5)/d
        ci=[center-half,center+half]
    else: ci=None
    return {"selected":int(n),"total":len(y),"coverage":n/len(y),"queue_correct":q,"queue_precision":q/n if n else None,
            "intent_correct":k,"intent_precision":k/n if n else None,"queue_precision_95ci":ci}


def evaluate():
    data=load_splits(); tests=data["test"]; x=[r["text"] for r in tests]; y=[r["label"] for r in tests]
    start=time.perf_counter(); predictor=Predictor(); cold=(time.perf_counter()-start)*1000
    probs=predictor.model.predict_proba(x); prediction=predictor.model.classes_[probs.argmax(axis=1)].tolist()
    counts=Counter(r["label"] for r in data["train"]); majority=counts.most_common(1)[0][0]
    words={"境外用卡":["国外","境外","出国"],"修改地址":["地址","搬家"],"应用故障":["应用","软件","打不开"],"取款限额":["限额","取多少"],"查询余额":["余额","多少钱"],"企业贷款":["贷款","企业"],"银行卡故障":["卡不能","刷不了"],"现金存款":["存款","存现金"],"自动扣款":["自动扣","直接扣"],"冻结账户":["冻结","被盗","挂失"],"大额支付":["大额","大笔"],"联名账户":["联名","共同账户"],"查询近期交易":["交易","流水"],"账单支付":["账单","缴费"]}
    keyword=[max(LABELS,key=lambda lab:sum(w in t for w in words[lab])) if any(w in t for ws in words.values() for w in ws) else majority for t in x]
    models={"多数类":score(y,[majority]*len(y)),"关键词":score(y,keyword)}
    for name,model in predictor.package["baselines"].items(): models[name]=score(y,model.predict(x))
    models["选定模型未校准"]=score(y,predictor.base.predict(x)); models["中文校准模型"]=score(y,prediction)
    confidence=probs.max(axis=1); ece=0.; reliability=[]
    for low in np.arange(0,1,.1):
        mask=(confidence>=low)&(confidence<low+.1 if low<.9 else confidence<=1)
        if mask.any():
            acc=float(np.mean(np.array(y)[mask]==np.array(prediction)[mask])); conf=float(confidence[mask].mean())
            ece+=mask.mean()*abs(acc-conf); reliability.append({"下界":float(low),"数量":int(mask.sum()),"正确率":acc,"平均概率":conf})
    records=[]; performance=[]; http_times=[]; workflow=[]
    with tempfile.TemporaryDirectory() as directory:
        agent=Agent(predictor,Store(Path(directory)/"evaluation.sqlite"))
        for row in tests:
            r=agent.submit(row["text"],row["id"]); records.append({"source_id":row["id"],"truth":row["label"],"prediction":r["suggested_intent"],"probability":r["candidates"][0]["probability"],
                "queue_correct":MAPPING[row["label"]]==r["suggested_queue"],"automatic":r["mode"]=="automatic","text":row["text"],"review_reasons":r["review_reasons"]})
        for i,row in enumerate(tests[:28]):
            r=agent.submit(row["text"],"flow-"+str(i)); before=r["status"]
            if before=="needs_review": r=agent.store.review(r["id"],row["label"],"自动化流程测试：按真值核验复核接口，不是真人实验")
            workflow.append({"source_id":row["id"],"before":before,"truth":row["label"],"final":r["final_intent"],"queue_correct":r["final_queue"]==MAPPING[row["label"]]})
        for i in range(100):
            start=time.perf_counter(); agent.submit(x[i%len(x)],"speed-"+str(i)); performance.append((time.perf_counter()-start)*1000)
        client=create_app(agent).test_client()
        for i in range(100):
            start=time.perf_counter(); response=client.post("/api/tickets",json={"text":x[i%len(x)],"ticket_id":"http-"+str(i)})
            if response.status_code!=200: raise RuntimeError("HTTP性能请求失败")
            http_times.append((time.perf_counter()-start)*1000)
        from tests.cases import CASES
        from tests.test_agent import run_case
        boundary=[{**c,"actual":run_case(c,agent)} for c in CASES]
    masks=[r["automatic"] for r in records]
    no_gate=[]
    for text,pr in zip(x,probs):
        order=np.argsort(pr)[-3:][::-1]; candidates=[{"intent":str(predictor.model.classes_[i]),"probability":float(pr[i])} for i in order]
        no_gate.append(not decide(text,candidates,{"probability":0.,"margin":0.}))
    result={"model_version":predictor.metadata["version"],"test_count":len(y),"test_source":"中文子集自建保留测试集；无官方测试划分",
            "models":models,"routing":selection_metrics(y,prediction,masks),
            "ablation":{"全部直接分流":selection_metrics(y,prediction,[True]*len(y)),"去掉概率门槛":selection_metrics(y,prediction,no_gate)},
            "policy":predictor.metadata["policy"],"ece_10bins":float(ece),
            "boundary":{"passed":sum(r["actual"]==r["expected"] for r in boundary),"total":len(boundary)},
            "workflow":{"total":len(workflow),"automatic":sum(r["before"]=="closed" for r in workflow),
                        "automatic_queue_correct":sum(r["before"]=="closed" and r["queue_correct"] for r in workflow),
                        "oracle_review_queue_correct":sum(r["queue_correct"] for r in workflow)},
            "performance":{"samples":100,"median_ms":float(np.median(performance)),"p95_ms":float(np.percentile(performance,95)),"cold_model_load_ms":cold},
            "http_performance":{"samples":100,"median_ms":float(np.median(http_times)),"p95_ms":float(np.percentile(http_times,95))},
            "environment":{"系统":platform.platform(),"Python":platform.python_version(),"说明":"单并发CPU测量；HTTP为进程内客户端，不含网络和浏览器，不衡量人工耗时"}}
    write_json(ROOT/"reports/evaluation.json",result); write_json(ROOT/"reports/test_predictions.json",records)
    write_json(ROOT/"reports/error_cases.json",[r for r in records if r["truth"]!=r["prediction"]])
    write_json(ROOT/"reports/classification_report.json",classification_report(y,prediction,labels=LABELS,output_dict=True,zero_division=0))
    write_json(ROOT/"reports/reliability.json",reliability)
    write_json(ROOT/"reports/boundary_results.json",boundary); write_json(ROOT/"reports/workflow_results.json",workflow)
    write_json(ROOT/"reports/performance_samples.json",performance); write_json(ROOT/"reports/http_performance_samples.json",http_times)
    with (ROOT/"reports/confusion_matrix.csv").open("w",encoding="utf-8-sig",newline="") as f:
        writer=csv.writer(f); writer.writerow(["真实/预测"]+LABELS)
        for label,row in zip(LABELS,confusion_matrix(y,prediction,labels=LABELS)): writer.writerow([label]+row.tolist())
    print(json.dumps(result,ensure_ascii=True,indent=2))
    return result


if __name__=="__main__": evaluate()
