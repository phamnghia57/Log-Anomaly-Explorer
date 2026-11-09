"""Aggregate raw samples without removing failures or averaging round percentiles."""
from collections import Counter
import csv
import hashlib
import json
import math
from pathlib import Path

HERE=Path(__file__).resolve().parent
def q(values,p):return sorted(values)[math.ceil(p*len(values))-1] if values else None
runs=[json.loads((folder/'results.json').read_text()) for folder in [HERE,HERE/'continuation']]
rows=[]
for folder in [HERE,HERE/'continuation']:
    rows += [dict(json.loads(line),sample_file=str((folder/'samples.jsonl').relative_to(HERE)))
             for line in (folder/'samples.jsonl').read_text().splitlines() if line]
summaries=[]
for size in [0,2,100]:
    allrows=[r for r in rows if r['history_size']==size]
    measured=[r for r in allrows if not r['warmup']]
    success=[r for r in measured if r['status']==200]
    values=[r['latency_ms'] for r in success]
    for round_id in set(r['round'] for r in allrows):
        batch=[r for r in allrows if r['round']==round_id]
        assert len(batch)==60 and len({r['cluster'] for r in batch})==60
    recorded=next((c for run in runs for c in run.get('classes',[]) if c['history_size']==size),{})
    s={'history_size':size,'workers':60,'warmup_requests':len(allrows)-len(measured),
       'planned_measured_requests':3000,'actual_measured_requests':len(measured),'successful':len(success),
       'http_conflicts':sum(r['status']==409 for r in measured),
       'other_http_errors':sum(r['status'] not in [None,200,409] for r in measured),
       'network_errors':sum(r['status'] is None for r in measured),
       'timeouts':sum('Timeout' in (r['error'] or '') for r in measured),
       'errors':sum(r['status']!=200 for r in measured),
       'successful_restoration_mismatches':sum(not r['persisted_correct'] for r in success),
       'failed_requests_not_restored':sum(not r['persisted_correct'] for r in measured if r['status']!=200),
       'mean_ms':sum(values)/len(values) if values else None,'p50_ms':q(values,.5),'p95_ms':q(values,.95),
       'p99_ms':q(values,.99),'max_success_ms':max(values) if values else None,
       'max_all_attempts_ms':max(r['latency_ms'] for r in measured) if measured else None,
       'throughput_requests_s':recorded.get('throughput_requests_s'),
       'response_body_bytes_min':min(r['response_bytes'] for r in success) if success else None,
       'response_body_bytes_max':max(r['response_bytes'] for r in success) if success else None,
       'compact_request_body_bytes':sorted({len(json.dumps({'expected_revision':r['expected_revision']},separators=(',',':')).encode()) for r in measured}),
       'reason_for_reduced_count':None if len(measured)==3000 else runs[0].get('failure_or_blocker')}
    s['target']='NOT MET' if s['errors'] or s['successful_restoration_mismatches'] or (s['p95_ms'] is not None and s['p95_ms']>2000) else 'MET' if len(measured)==3000 else 'INCONCLUSIVE'
    summaries.append(s)
report={'workloads':summaries,'overall':'NOT MET' if any(s['target']=='NOT MET' for s in summaries) else 'MET' if all(s['target']=='MET' for s in summaries) else 'INCONCLUSIVE',
        'raw_sample_count_including_warmup':len(rows),'measured_samples':sum(s['actual_measured_requests'] for s in summaries),
        'errors_retained':[r for r in rows if r['status']!=200 or not r['persisted_correct']],
        'contention':runs[1].get('contention',[]),'all_owned_containers_removed':all(r.get('owned_container_removed') for r in runs),
        'tracked_source_preserved':all(not r.get('changed_tracked_files') for r in runs),
        'raw_sha256':{str((folder/'samples.jsonl').relative_to(HERE)):hashlib.sha256((folder/'samples.jsonl').read_bytes()).hexdigest() for folder in [HERE,HERE/'continuation']}}
(HERE/'summary.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
with (HERE/'comparison.csv').open('w',newline='',encoding='utf-8') as out:
    writer=csv.DictWriter(out,fieldnames=list(summaries[0]));writer.writeheader();writer.writerows(summaries)
print(json.dumps({'overall':report['overall'],'workloads':summaries,'contention_count':len(report['contention'])}))
