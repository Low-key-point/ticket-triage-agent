"""中文字符特征分类、训练折内选型、独立校准与验证集阈值选择。"""
import hashlib
import json
import platform
import time
import joblib
import numpy as np
import sklearn
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.svm import LinearSVC
from sklearn.linear_model import LogisticRegression
from sklearn.naive_bayes import MultinomialNB
from sklearn.model_selection import StratifiedGroupKFold, cross_val_score
from sklearn.calibration import CalibratedClassifierCV
from sklearn.frozen import FrozenEstimator
from sklearn.metrics import accuracy_score, f1_score
from .data import ROOT, load_splits, write_json
from .policy import sanitize_texts, input_reasons
from .knowledge import MAPPING, SENSITIVE


def pipeline(kind,C=1.,ngram=(1,3)):
    classifier=LinearSVC(C=C,random_state=42) if kind=="线性支持向量机" else LogisticRegression(C=C,max_iter=2000,random_state=42) if kind=="逻辑回归" else MultinomialNB(alpha=1.)
    return Pipeline([("normalize",FunctionTransformer(sanitize_texts)),("features",TfidfVectorizer(analyzer="char",ngram_range=ngram,sublinear_tf=True,max_features=40000)),
                     ("classifier",classifier)])


def train():
    start=time.perf_counter(); data=load_splits()
    def xy(part): return [r["text"] for r in data[part]],[r["label"] for r in data[part]]
    tx,ty=xy("train"); cx,cy=xy("calibration"); vx,vy=xy("validation")
    groups=[r["group"] for r in data["train"]]
    specs=[(kind,C,ngram) for kind in ["线性支持向量机","逻辑回归"] for C in [1.,4.] for ngram in [(1,3),(2,4)]]
    cv=StratifiedGroupKFold(3,shuffle=True,random_state=45)
    results=[]
    for kind,C,ngram in specs:
        scores=cross_val_score(pipeline(kind,C,ngram),tx,ty,groups=groups,cv=cv,scoring="f1_macro",n_jobs=1)
        results.append({"算法":kind,"C":C,"字符范围":list(ngram),"三折宏F1":scores.tolist(),"平均宏F1":float(scores.mean())})
    best=max(results,key=lambda r:r["平均宏F1"])
    base=pipeline(best["算法"],best["C"],tuple(best["字符范围"])).fit(tx,ty)
    model=CalibratedClassifierCV(FrozenEstimator(base),method="sigmoid").fit(cx,cy)
    probs=model.predict_proba(vx); ranked=np.sort(probs,axis=1); prediction=model.classes_[probs.argmax(axis=1)]
    allowed=np.array([not input_reasons(t) and p not in SENSITIVE for t,p in zip(vx,prediction)])
    searches=[]
    for p in [.25,.35,.45,.55,.65,.75,.85,.95]:
        for m in [0.,.05,.10,.20]:
            mask=allowed&(ranked[:,-1]>=p)&((ranked[:,-1]-ranked[:,-2])>=m)
            n=int(mask.sum()); correct=sum(MAPPING[a]==MAPPING[b] for a,b,on in zip(prediction,vy,mask) if on)
            searches.append({"probability":p,"margin":m,"count":n,"coverage":n/len(vy),"queue_precision":correct/n if n else None})
    feasible=[s for s in searches if s["count"]>=10 and s["queue_precision"]>=.95]
    policy=max(feasible,key=lambda s:(s["coverage"],s["queue_precision"],s["probability"])) if feasible else {"probability":1.1,"margin":0.,"count":0,"coverage":0.,"queue_precision":None}
    sources={n:hashlib.sha256((ROOT/"triage"/n).read_text(encoding="utf-8").replace("\r\n","\n").encode()).hexdigest() for n in ["data.py","train.py","policy.py","knowledge.py"]}
    version=hashlib.sha256(json.dumps({"sources":sources,"split":json.loads((ROOT/"reports/data_manifest.json").read_text(encoding="utf-8")),"best":best},sort_keys=True).encode()).hexdigest()[:12]
    metadata={"version":version,"language":"中文","dataset":"MInDS-14中文子集","classes":len(MAPPING),"policy":policy,
              "selected_spec":best,"validation":{"accuracy":float(accuracy_score(vy,prediction)),"macro_f1":float(f1_score(vy,prediction,average="macro"))},
              "sklearn":sklearn.__version__,"python":platform.python_version(),"source_hashes":sources,"test_used_for_selection":False,
              "training_seconds":time.perf_counter()-start}
    baselines={"朴素贝叶斯":pipeline("朴素贝叶斯").fit(tx,ty),"字符逻辑回归":pipeline("逻辑回归").fit(tx,ty)}
    (ROOT/"models").mkdir(exist_ok=True)
    joblib.dump({"model":model,"base_model":base,"metadata":metadata,"baselines":baselines},ROOT/"models/model.joblib",compress=3)
    write_json(ROOT/"reports/cv_results.json",results); write_json(ROOT/"reports/threshold_search.json",searches)
    write_json(ROOT/"reports/model_metadata.json",metadata)
    print(json.dumps(metadata,ensure_ascii=True))


if __name__=="__main__": train()
