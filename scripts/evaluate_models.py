#!/usr/bin/env python3
"""Opt-in qualitative canary comparison; never treats keyword matches as proof.

No model calls unless --run is explicitly supplied. Store outputs in .local/evals.
"""
from __future__ import annotations
import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from pdvl.config import home
from pdvl.prompts import MODE_PROMPTS
from pdvl.providers import pick_model, generate, ProviderError

CASES=[
  {'id':'rg_csk', 'mode':'verify', 'question':'Derive the RG equation for K(b1,μ)-K(b2,μ). State the precise conditions of RG invariance and what the result does not establish.', 'expert_check':'Common anomalous dimensions; difference scale independent; no automatic experimental observability.'},
  {'id':'eec_overclaim', 'mode':'investigate', 'question':'A proposal claims RG invariance of Delta K guarantees model-independent extraction from any two-scale EEC comparison. Test this inference and identify where additional TMD inputs and finite-bin uncertainties enter.', 'expert_check':'Must not imply RG invariance alone cancels process-specific functions or establishes extraction.'},
  {'id':'scientific_prose', 'mode':'write', 'question':'Write one mature PRL-style introductory paragraph explaining why testing nonperturbative TMD evolution across independent processes is meaningful. Avoid inflated claims; do not call unknown nuisance cancellations proven.', 'expert_check':'Natural conceptual argument; no engineering-format bullets; precise caveat if needed.'}
]

async def run(model_ids):
    outfile=home()/'evals'/f"model_canary_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.jsonl"
    outfile.parent.mkdir(parents=True, exist_ok=True)
    with outfile.open('w',encoding='utf-8') as f:
        for case in CASES:
            for mid in model_ids:
                model=pick_model(case['mode'],mid)
                try:
                    text,metadata=await generate(model, MODE_PROMPTS[case['mode']],
                               [{'role':'user','content':case['question']}])
                    entry={'case':case['id'],'model_id':mid,'meta':metadata,'answer':text,
                           'expert_check':case['expert_check'],'status':'awaits_human_scientific_review'}
                except ProviderError as e:
                    entry={'case':case['id'],'model_id':mid,'error':str(e),'status':'blocked'}
                f.write(json.dumps(entry,ensure_ascii=False)+'\n')
                print(case['id'],mid,entry['status'])
    print('Results:',outfile)

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--models',nargs='+',default=['gpt-sol','deepseek-pro'])
    p.add_argument('--run',action='store_true',help='Explicitly permit real paid provider API requests')
    args=p.parse_args()
    if not args.run:
        print('Dry run: no provider requests. Use --run to submit real, potentially billable evaluation tasks.')
        for case in CASES: print(case['id'],case['expert_check'])
        sys.exit(0)
    asyncio.run(run(args.models))
