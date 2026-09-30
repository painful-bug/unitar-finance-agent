"""Isolated worker: PYTHONPATH points only to a frozen version's src directory."""
from __future__ import annotations

import inspect
import json
import sys
from datetime import date
from pathlib import Path

from groq import Groq
import finance_agent.agent as agent_module
from finance_agent.agent import GroqProvider, run_agent
from finance_agent.finance import FinanceData, load_csv
from finance_agent.models import Session


from evaluation_transport import paced_completion


def main():
    request, response = map(Path, sys.argv[1:])
    job = json.loads(request.read_text())
    case, version = job['case'], job['version']
    source_file = Path(agent_module.__file__).resolve()
    expected = request.parent / 'sources' / version / 'src'
    if not source_file.is_relative_to(expected):
        raise RuntimeError(f'Agent import escaped frozen snapshot: {source_file}')
    print(f'  Frozen agent source: {source_file}', flush=True)
    provider = GroqProvider(job['agent_model'], client=Groq(timeout=30, max_retries=1))
    transport = []
    provider.client.chat.completions.create = paced_completion(provider.client, request.parent/'groq-pacing.json', transport)
    anchor = date(2026, 8, 15)
    session = Session(session_id=f"eval-{case['id']}", data=FinanceData(load_csv(job['csv_text']), anchor),
                      as_of_date=anchor, context_mode='auto')
    manager = None
    if version == 'final':
        from finance_agent.context import ContextManager
        manager = ContextManager()
    events = []
    def event_callback(event):
        data = event.model_dump(mode='json')
        events.append(data)
        if data['stage'] in {'context', 'model'} and data['state'] in {'started', 'warning', 'failed'}:
            print(f"  [{data['stage']}/{data['state']}] step {data.get('step')} {data['payload']}", flush=True)
    turns = []
    final = {'answer': '', 'status': 'worker_error'}
    try:
        for turn_number, question in enumerate([*case.get('prelude', []), case['question']], 1):
            print(f"  Turn {turn_number}: {question}", flush=True)
            extra = {'event_callback': event_callback} if 'event_callback' in inspect.signature(run_agent).parameters else {}
            result = run_agent(session, question, provider, context_manager=manager, **extra)
            final = result.model_dump(mode='json')
            turns.append({'question': question, **final})
            for trace in final['trace']:
                print(f"    TOOL {trace['tool']} {json.dumps(trace['arguments'])}", flush=True)
                print('    RESULT ' + json.dumps(trace.get('result') or {'error': trace.get('error')}), flush=True)
            print(f"    ANSWER ({result.status}, {result.steps} steps): {result.answer}", flush=True)
            context = final.get('context', {})
            if context.get('strategy', 'none') != 'none':
                print('    CONTEXT ' + json.dumps(context), flush=True)
            if result.status != 'ok':
                break
    except Exception as exc:
        final = {'answer': '', 'status': 'worker_error', 'error': f'{type(exc).__name__}: {exc}'}
        print('    EXECUTION ERROR: ' + final['error'], flush=True)
    finally:
        provider.client.close()
    response.write_text(json.dumps({'id': case['id'], 'version': version, 'repeat': job['repeat'],
                                    'answer': final['answer'], 'status': final['status'],
                                    'turns': turns, 'events': events, 'transport': transport, 'error': final.get('error')}, indent=2))


if __name__ == '__main__':
    main()
