"""
Scientific Evaluation Framework for NL-SPARQL Translation
===========================================================
Implements standard metrics from the Text-to-SQL/SPARQL literature:

METRICS:
1. Execution Accuracy (EA): Does the generated query execute without errors?
2. Result Accuracy (RA): Does it return at least the expected minimum results?
3. Component Match F1: Do the correct entities/properties appear in the query?
   - Precision: what fraction of generated components are expected
   - Recall: what fraction of expected components are present
   - F1: harmonic mean
4. BLEU Score: N-gram overlap between generated and gold-standard SPARQL
5. Execution Time: Generation + execution latency

Usage:
    python tests/evaluate.py
    python tests/evaluate.py --models "llama3.3:latest,llama3:latest"
    python tests/evaluate.py --domain "Diseases"
    python tests/evaluate.py --quick
    python tests/evaluate.py --save evaluation_results.json
"""

import os, sys, json, time, math, yaml, glob, argparse, re
from datetime import datetime
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src import llm_client, nl_to_sparql, sparql_executor

def compute_bleu(reference, hypothesis, max_n=4):
    def tokenize(t): return re.findall(r'\w+|[^\s\w]', t.lower())
    ref, hyp = tokenize(reference), tokenize(hypothesis)
    if not hyp: return 0.0
    bp = 1.0 if len(hyp) >= len(ref) else math.exp(1 - len(ref)/max(len(hyp),1))
    precs = []
    for n in range(1, max_n+1):
        rng = Counter(tuple(ref[i:i+n]) for i in range(len(ref)-n+1))
        hng = Counter(tuple(hyp[i:i+n]) for i in range(len(hyp)-n+1))
        clip = sum(min(hng[g], rng[g]) for g in hng)
        total = sum(hng.values())
        precs.append(clip/total if total else 0)
    log_avg = 0
    for p in precs:
        if p == 0: return 0.0
        log_avg += math.log(p)/max_n
    return bp * math.exp(log_avg)

def compute_component_f1(expected, sparql):
    if not expected: return {"precision":1,"recall":1,"f1":1,"found":[],"missing":[]}
    low = sparql.lower()
    found = [c for c in expected if c.lower() in low]
    missing = [c for c in expected if c.lower() not in low]
    rec = len(found)/len(expected)
    f1 = rec  # simplified
    return {"precision":round(rec,4),"recall":round(rec,4),"f1":round(f1,4),"found":found,"missing":missing}

GOLD_STANDARD = [
    {"id":"D01","domain":"Diseases","complexity":"simple","question":"List 10 diseases",
     "gold_sparql":"SELECT DISTINCT ?disease ?diseaseLabel WHERE { ?disease wdt:P31 wd:Q12136 . SERVICE wikibase:label { bd:serviceParam wikibase:language \"en\" . } } LIMIT 10",
     "expected_components":["wdt:P31","wd:Q12136","LIMIT"],"min_results":5},
    {"id":"D02","domain":"Diseases","complexity":"simple","question":"What are the symptoms of diabetes?",
     "gold_sparql":"SELECT DISTINCT ?symptom ?symptomLabel WHERE { wd:Q12206 wdt:P780 ?symptom . SERVICE wikibase:label { bd:serviceParam wikibase:language \"en\" . } }",
     "expected_components":["wdt:P780","wd:Q12206"],"min_results":1},
    {"id":"D03","domain":"Diseases","complexity":"simple","question":"Which drugs are used to treat malaria?",
     "gold_sparql":"SELECT DISTINCT ?drug ?drugLabel WHERE { wd:Q12156 wdt:P2176 ?drug . SERVICE wikibase:label { bd:serviceParam wikibase:language \"en\" . } }",
     "expected_components":["wdt:P2176","wd:Q12156"],"min_results":1},
    {"id":"D04","domain":"Diseases","complexity":"medium","question":"List diseases with their ICD-10 codes",
     "gold_sparql":"SELECT DISTINCT ?disease ?diseaseLabel ?icd WHERE { ?disease wdt:P31 wd:Q12136 . ?disease wdt:P494 ?icd . SERVICE wikibase:label { bd:serviceParam wikibase:language \"en\" . } } LIMIT 20",
     "expected_components":["wdt:P31","wd:Q12136","wdt:P494"],"min_results":3},
    {"id":"D05","domain":"Diseases","complexity":"complex","question":"Which diseases are caused by bacteria?",
     "gold_sparql":"SELECT DISTINCT ?disease ?diseaseLabel WHERE { ?disease wdt:P31 wd:Q12136 . ?disease wdt:P828 ?agent . ?agent wdt:P31 wd:Q10876 . SERVICE wikibase:label { bd:serviceParam wikibase:language \"en\" . } } LIMIT 20",
     "expected_components":["wdt:P828","wd:Q10876","wdt:P31","wd:Q12136"],"min_results":1},
    {"id":"M01","domain":"Movies (DBpedia)","complexity":"simple","question":"List 10 movies",
     "gold_sparql":"SELECT DISTINCT ?film ?name WHERE { ?film a dbo:Film . ?film rdfs:label ?name . FILTER(LANG(?name) = \"en\") } LIMIT 10",
     "expected_components":["dbo:Film","rdfs:label","FILTER","LIMIT"],"min_results":5},
    {"id":"M02","domain":"Movies (DBpedia)","complexity":"simple","question":"List movies directed by Steven Spielberg",
     "gold_sparql":"SELECT DISTINCT ?film ?name WHERE { ?film a dbo:Film . ?film dbo:director dbr:Steven_Spielberg . ?film rdfs:label ?name . FILTER(LANG(?name) = \"en\") }",
     "expected_components":["dbo:Film","dbo:director","Steven_Spielberg"],"min_results":1},
    {"id":"M03","domain":"Movies (DBpedia)","complexity":"medium","question":"Who directed Inception?",
     "gold_sparql":"SELECT DISTINCT ?director ?name WHERE { dbr:Inception dbo:director ?director . ?director rdfs:label ?name . FILTER(LANG(?name) = \"en\") }",
     "expected_components":["dbo:director","Inception"],"min_results":1},
    {"id":"A01","domain":"Astronomy (Wikidata)","complexity":"simple","question":"List all planets in our Solar System",
     "gold_sparql":"SELECT DISTINCT ?planet ?planetLabel WHERE { ?planet wdt:P31 wd:Q634 . SERVICE wikibase:label { bd:serviceParam wikibase:language \"en\" . } }",
     "expected_components":["wdt:P31","wd:Q634"],"min_results":5},
    {"id":"A02","domain":"Astronomy (Wikidata)","complexity":"simple","question":"List 10 galaxies",
     "gold_sparql":"SELECT DISTINCT ?galaxy ?galaxyLabel WHERE { ?galaxy wdt:P31 wd:Q318 . SERVICE wikibase:label { bd:serviceParam wikibase:language \"en\" . } } LIMIT 10",
     "expected_components":["wdt:P31","wd:Q318","LIMIT"],"min_results":5},
    {"id":"A03","domain":"Astronomy (Wikidata)","complexity":"medium","question":"Which moons orbit Jupiter?",
     "gold_sparql":"SELECT DISTINCT ?moon ?moonLabel WHERE { ?moon wdt:P31 wd:Q25257 . ?moon wdt:P397 wd:Q319 . SERVICE wikibase:label { bd:serviceParam wikibase:language \"en\" . } }",
     "expected_components":["wd:Q25257","wd:Q319","wdt:P397"],"min_results":1},
    {"id":"P01","domain":"Philosophy (Wikidata)","complexity":"simple","question":"List 10 philosophers",
     "gold_sparql":"SELECT DISTINCT ?philosopher ?philosopherLabel WHERE { ?philosopher wdt:P106 wd:Q4964182 . SERVICE wikibase:label { bd:serviceParam wikibase:language \"en\" . } } LIMIT 10",
     "expected_components":["wdt:P106","wd:Q4964182","LIMIT"],"min_results":5},
    {"id":"P02","domain":"Philosophy (Wikidata)","complexity":"simple","question":"Who influenced Immanuel Kant?",
     "gold_sparql":"SELECT DISTINCT ?influence ?influenceLabel WHERE { wd:Q9312 wdt:P737 ?influence . SERVICE wikibase:label { bd:serviceParam wikibase:language \"en\" . } }",
     "expected_components":["wdt:P737","wd:Q9312"],"min_results":1},
    {"id":"P03","domain":"Philosophy (Wikidata)","complexity":"complex","question":"List German philosophers born in the 19th century",
     "gold_sparql":"SELECT DISTINCT ?philosopher ?philosopherLabel ?birth WHERE { ?philosopher wdt:P106 wd:Q4964182 . ?philosopher wdt:P27 wd:Q183 . ?philosopher wdt:P569 ?birth . FILTER(YEAR(?birth) >= 1800 && YEAR(?birth) < 1900) SERVICE wikibase:label { bd:serviceParam wikibase:language \"en\" . } }",
     "expected_components":["wdt:P106","wd:Q4964182","wd:Q183","wdt:P569","FILTER"],"min_results":1},
    {"id":"B01","domain":"Books (DBpedia)","complexity":"simple","question":"List 10 novels",
     "gold_sparql":"SELECT DISTINCT ?book ?name WHERE { ?book a dbo:Novel . ?book rdfs:label ?name . FILTER(LANG(?name) = \"en\") } LIMIT 10",
     "expected_components":["dbo:Novel","rdfs:label","FILTER","LIMIT"],"min_results":5},
    {"id":"B02","domain":"Books (DBpedia)","complexity":"simple","question":"List books written by George Orwell",
     "gold_sparql":"SELECT DISTINCT ?book ?name WHERE { ?book a dbo:Book . ?book dbo:author dbr:George_Orwell . ?book rdfs:label ?name . FILTER(LANG(?name) = \"en\") }",
     "expected_components":["dbo:author","George_Orwell"],"min_results":1},
]

def run_test(case, config, model):
    r = {"id":case["id"],"question":case["question"],"domain":case["domain"],
         "complexity":case["complexity"],"model":model,"generated_sparql":"",
         "gold_sparql":case["gold_sparql"],"execution_accuracy":False,
         "result_accuracy":False,"result_count":0,"component_precision":0,
         "component_recall":0,"component_f1":0,"components_found":[],
         "components_missing":[],"bleu":0,"generation_time_s":0,
         "execution_time_s":0,"total_time_s":0,"error":None}
    t0=time.time()
    try:
        raw=nl_to_sparql.translate(case["question"],config,model=model)
        cleaned=sparql_executor.clean_sparql(raw)
        r["generated_sparql"]=cleaned
        r["generation_time_s"]=round(time.time()-t0,2)
    except Exception as e:
        r["error"]=f"Gen:{str(e)[:200]}"
        r["generation_time_s"]=round(time.time()-t0,2)
        return r
    if not cleaned or cleaned.startswith("[ERROR]"):
        r["error"]=f"Empty:{cleaned[:200]}"
        return r
    r["bleu"]=round(compute_bleu(case["gold_sparql"],cleaned),4)
    comp=compute_component_f1(case["expected_components"],cleaned)
    r["component_precision"]=comp["precision"]
    r["component_recall"]=comp["recall"]
    r["component_f1"]=comp["f1"]
    r["components_found"]=comp["found"]
    r["components_missing"]=comp["missing"]
    t1=time.time()
    try:
        ex=sparql_executor.execute(cleaned,config["endpoint"])
        r["execution_time_s"]=round(time.time()-t1,2)
        if ex["success"]:
            r["execution_accuracy"]=True
            r["result_count"]=len(ex["results"])
            r["result_accuracy"]=r["result_count"]>=case.get("min_results",0)
        else:
            r["error"]=f"Exec:{ex.get('error','')[:200]}"
    except Exception as e:
        r["error"]=f"ExecErr:{str(e)[:200]}"
        r["execution_time_s"]=round(time.time()-t1,2)
    r["total_time_s"]=round(r["generation_time_s"]+r["execution_time_s"],2)
    return r

def print_result(r):
    ok="PASS" if (r["execution_accuracy"] and r["result_accuracy"] and r["component_f1"]>=0.5) else "FAIL"
    print(f"  [{ok}] {r['id']:5s} | EA:{'✓' if r['execution_accuracy'] else '✗'} RA:{'✓' if r['result_accuracy'] else '✗'} F1:{r['component_f1']:.2f} BLEU:{r['bleu']:.2f} | n={r['result_count']:4d} t={r['total_time_s']:5.1f}s | {r['question'][:42]}")
    if r["components_missing"]: print(f"         missing: {r['components_missing']}")
    if r["error"]: print(f"         error: {r['error'][:100]}")

def print_summary(model, results):
    n=len(results)
    if not n: return
    ea=sum(1 for r in results if r["execution_accuracy"])/n
    ra=sum(1 for r in results if r["result_accuracy"])/n
    f1=sum(r["component_f1"] for r in results)/n
    bl=sum(r["bleu"] for r in results)/n
    t=sum(r["total_time_s"] for r in results)/n
    print(f"\n  Model: {model}")
    print(f"  {'─'*55}")
    print(f"  Execution Accuracy:  {ea:.1%}")
    print(f"  Result Accuracy:     {ra:.1%}")
    print(f"  Avg Component F1:    {f1:.3f}")
    print(f"  Avg BLEU:            {bl:.3f}")
    print(f"  Avg Time:            {t:.1f}s")

def print_comparison(all_results):
    models=list(all_results.keys())
    if len(models)<2: return
    print(f"\n{'='*80}\nMODEL COMPARISON\n{'='*80}")
    h=f"{'Metric':<28s}"
    for m in models: h+=f" | {m[:18]:>18s}"
    print(h); print("─"*len(h))
    for label,fn in [("Execution Accuracy",lambda rs:f"{sum(1 for r in rs if r['execution_accuracy'])/len(rs):.0%}"),
                     ("Result Accuracy",lambda rs:f"{sum(1 for r in rs if r['result_accuracy'])/len(rs):.0%}"),
                     ("Avg Component F1",lambda rs:f"{sum(r['component_f1'] for r in rs)/len(rs):.3f}"),
                     ("Avg BLEU",lambda rs:f"{sum(r['bleu'] for r in rs)/len(rs):.3f}"),
                     ("Avg Time (s)",lambda rs:f"{sum(r['total_time_s'] for r in rs)/len(rs):.1f}s")]:
        row=f"{label:<28s}"
        for m in models: row+=f" | {fn(all_results[m]):>18s}"
        print(row)
    for title,key in [("BY COMPLEXITY","complexity"),("BY DOMAIN","domain")]:
        print(f"\n{'─'*80}\n{title}\n{'─'*80}")
        vals=sorted(set(r[key] for rs in all_results.values() for r in rs))
        for v in vals:
            row=f"  {v[:26]:<28s}"
            for m in models:
                rs=[r for r in all_results[m] if r[key]==v]
                if rs:
                    ea=sum(1 for r in rs if r["execution_accuracy"])/len(rs)
                    f1=sum(r["component_f1"] for r in rs)/len(rs)
                    row+=f" | {'EA:'+f'{ea:.0%}'+' F1:'+f'{f1:.2f}':>18s}"
                else: row+=f" | {'N/A':>18s}"
            print(row)

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--models",default=None)
    p.add_argument("--domain",default=None)
    p.add_argument("--complexity",default=None)
    p.add_argument("--save",default=None)
    p.add_argument("--quick",action="store_true")
    a=p.parse_args()
    models=[m.strip() for m in a.models.split(",")] if a.models else ["llama3.3:latest","llama3:latest"]
    avail=llm_client.list_models()
    if avail: models=[m for m in models if m in avail or not print(f"WARN: {m} not found")]
    configs={}
    for fp in glob.glob("configs/*.yaml"):
        with open(fp) as f:
            c=yaml.safe_load(f); configs[c.get("domain_name",os.path.basename(fp))]=c
    cases=GOLD_STANDARD[:]
    if a.domain: cases=[c for c in cases if c["domain"]==a.domain]
    if a.complexity: cases=[c for c in cases if c["complexity"]==a.complexity]
    if a.quick:
        q,s=[],{}
        for c in cases:
            d=c["domain"]; s[d]=s.get(d,0)
            if s[d]<2: q.append(c); s[d]+=1
        cases=q
    cases=[c for c in cases if c["domain"] in configs]
    if not cases: print("No cases. Domains:",list(configs.keys())); return
    print(f"{'='*80}\nNL-SPARQL SCIENTIFIC EVALUATION\n{'='*80}")
    print(f"Date:    {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Models:  {', '.join(models)}")
    print(f"Cases:   {len(cases)}")
    print(f"Metrics: Execution Accuracy, Result Accuracy, Component F1, BLEU\n")
    all_results={}
    for model in models:
        print(f"\n{'━'*80}\n  MODEL: {model}\n{'━'*80}")
        mr=[]
        for i,case in enumerate(cases,1):
            cfg=configs.get(case["domain"])
            if not cfg: continue
            print(f"\n  [{i}/{len(cases)}] {case['question']}")
            r=run_test(case,cfg,model); print_result(r); mr.append(r); time.sleep(1)
        all_results[model]=mr; print_summary(model,mr)
    if len(models)>1: print_comparison(all_results)
    if a.save:
        out={"timestamp":datetime.now().isoformat(),"models":models,
             "metrics":["execution_accuracy","result_accuracy","component_f1","bleu"],
             "case_count":len(cases),"summaries":{},"detailed_results":{}}
        for m,rs in all_results.items():
            n=len(rs)
            out["summaries"][m]={"execution_accuracy":round(sum(1 for r in rs if r["execution_accuracy"])/n,4),
                "result_accuracy":round(sum(1 for r in rs if r["result_accuracy"])/n,4),
                "avg_component_f1":round(sum(r["component_f1"] for r in rs)/n,4),
                "avg_bleu":round(sum(r["bleu"] for r in rs)/n,4),
                "avg_time_s":round(sum(r["total_time_s"] for r in rs)/n,2)}
            out["detailed_results"][m]=rs
        with open(a.save,"w") as f: json.dump(out,f,indent=2,default=str)
        print(f"\nSaved: {a.save}")
    print(f"\nDone: {datetime.now().strftime('%H:%M:%S')}")

if __name__=="__main__": main()
