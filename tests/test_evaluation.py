import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from typesafe_sdk import SystemOneResponse

from finance_agent import evaluation as e
from finance_agent.threads import ChatStore


def response(confidence=.9, verdict='fail'):
    return SystemOneResponse.model_validate(dict(
        model=e.JEV_MODEL, usage={'input_tokens': 100, 'output_tokens': 20}, answers={
            'verdict': {'type': 'choice', 'choice': verdict, 'confidence': confidence,
                        'probabilities': {'pass': .1 if verdict == 'fail' else .9, 'fail': .9 if verdict == 'fail' else .1}},
            'quality': {'type': 'score', 'score': 2.5, 'confidence': confidence,
                        'probabilities': {0: 0, 1: 0, 2: .5, 3: .5, 4: 0},
                        'legend': dict(enumerate(e.SCORE_LEVELS))}}))


def test_frozen_cases_literal_matching_and_schema():
    cases = [e.GoldenCase.model_validate(c) for c in json.loads(Path('evals/golden.json').read_text())]
    assert len(cases) == 12
    assert sum(c.check_type == 'keyword' for c in cases) == 5
    assert len(next(c for c in cases if c.id == 'sixteen_turn_context').prelude) + 1 == 16
    assert e.check_keywords('WITHIN budget: 690.65', ['within', '690.65'])
    assert not e.check_keywords('690.64', ['690.65'])
    assert e.check_keywords('14500', ['450'])  # known notebook substring limitation, not a numeric parser
    with pytest.raises(ValidationError):
        e.GoldenCase(id='empty', question='q', check_type='keyword')
    for score in (0, 6):
        with pytest.raises(ValidationError):
            e.AnswerJudgment(passed=True, score=score, reasoning='bad')
    assert e.verify_reference(Path('evals/ledger.csv').read_text())['july_savings_rate'] == '36.99'


def test_independent_jev_and_auto_policy(monkeypatch):
    calls = []
    def llm(*args):
        calls.append('llm')
        return e.AnswerJudgment(passed=True, score=1, reasoning='Boolean remains authoritative.')
    monkeypatch.setattr(e, 'judge_answer', llm)
    monkeypatch.setattr(e, 'judge_with_jev', lambda *args: e.jev_judgment(response()))
    forced, raw = e.grade('q', 'a', 'c', 'jev')
    assert not forced.passed and forced.score == 3  # tied modes choose lower index + 1
    assert 'Code-generated summary' in forced.reasoning and raw['native_expected_score'] == 2.5
    assert not e.grade('q', 'a', 'c', 'auto')[0].passed  # confident fail never falls back
    assert calls == []
    monkeypatch.setattr(e, 'judge_with_jev', lambda *args: e.jev_judgment(response(.3)))
    assert not e.grade('q', 'a', 'c', 'jev')[0].passed  # forced uncertainty retains verdict
    judgment, metadata = e.grade('q', 'a', 'c', 'auto')
    assert judgment.passed and metadata['effective_judge'] == 'llm' and metadata['fallback_reason']
    assert calls == ['llm']
    def broken(*args):
        raise ValueError('missing questions')
    monkeypatch.setattr(e, 'judge_with_jev', broken)
    with pytest.raises(ValueError):
        e.grade('q', 'a', 'c', 'jev')
    assert e.grade('q', 'a', 'c', 'auto')[0].passed
    # Forced normal LLM must never call Jev.
    assert e.grade('q', 'a', 'c', 'llm')[0].passed


def test_notebook_routing_boolean_score_and_error_denominator(monkeypatch):
    calls = []
    def grade(question, answer, criteria, backend):
        calls.append((question, answer, backend))
        if answer == 'service fails':
            raise RuntimeError('provider outage')
        return e.AnswerJudgment(passed=True, score=1, reasoning='Pass boolean is direct.'), {}
    monkeypatch.setattr(e, 'grade', grade)
    cases = [dict(id='k', question='kw', check_type='keyword', must_include=['OK']),
             dict(id='j', question='judge', check_type='judge', criteria='c'),
             dict(id='error', question='judge error', check_type='judge', criteria='c'),
             dict(id='exec', question='bad execution', check_type='judge', criteria='c')]
    answers = [dict(answer=a, status=s, repeat=1) for a,s in [('ok','ok'), ('good','ok'), ('service fails','ok'), ('good','error')]]
    llm = e.run_eval('first', cases, answers, 'llm')
    jev = e.run_eval('first', cases, answers, 'jev')
    assert llm['pass_rate'] == jev['pass_rate'] == .5
    assert len(calls) == 4 and calls[0][1] == calls[2][1] == 'good'
    assert llm['results'][2]['judge_error'] and not llm['results'][3]['passed']
    checkpoints = []
    resumed = e.run_eval('first', cases, answers, 'llm', llm['results'][:2], lambda: checkpoints.append(True))
    assert resumed['pass_rate'] == .5 and len(checkpoints) == 2


def test_persistent_judge_selection_and_explicit_cli(monkeypatch, tmp_path):
    from finance_agent.server import SessionStore
    store = SessionStore(chat_store=ChatStore(tmp_path))
    assert store.get_app_settings().evaluation_judge == 'auto'
    store.update_app_settings(evaluation_judge='jev')
    assert SessionStore(chat_store=ChatStore(tmp_path)).get_app_settings().evaluation_judge == 'jev'
    with pytest.raises(ValidationError):
        store.update_app_settings(evaluation_judge='both')
    assert store.get_app_settings().evaluation_judge == 'jev'
    assert e.resolve_judge('llm', 'http://invalid') == ('llm', 'CLI override')
    async def settings(url):
        return {'evaluation_judge': 'jev'}
    monkeypatch.setattr(e, '_mcp_settings', settings)
    assert e.resolve_judge(None, 'http://explicit')[0] == 'jev'
    async def unavailable(url):
        raise ConnectionError('offline')
    monkeypatch.setattr(e, '_mcp_settings', unavailable)
    monkeypatch.setenv('FINANCE_CHAT_STORE_PATH', str(tmp_path))
    assert e.resolve_judge(None, None)[0] == 'jev'
    with pytest.raises(RuntimeError, match='Explicit MCP'):
        e.resolve_judge(None, 'http://explicit')


def test_historical_and_dirty_source_snapshots(tmp_path):
    snapshots = e.freeze_sources(tmp_path)
    assert snapshots['baseline']['commit'] == '8863d78fe080b70400c63a22aa609120e9107ea0'
    old = (tmp_path/'sources/baseline/src/finance_agent/agent.py').read_text()
    new = (tmp_path/'sources/final/src/finance_agent/agent.py').read_text()
    assert 'max_steps: int = 6' in old and 'max_steps: int = 15' in new
    assert not (tmp_path/'sources/baseline/src/finance_agent/context.py').exists()
    assert (tmp_path/'sources/final/src/finance_agent/context.py').read_bytes() == Path('src/finance_agent/context.py').read_bytes()
    assert snapshots['baseline']['snapshot_sha256'] != snapshots['final']['snapshot_sha256']


def test_shared_token_pacing_and_duration(monkeypatch, tmp_path):
    from finance_agent import evaluation_transport as worker
    assert worker.duration('1m2.5s') == 62.5
    assert worker.duration('37.5ms') == .0375
    assert worker.duration('2') == 2
    clock = [1000.0]
    sleeps = []
    monkeypatch.setattr(worker.time, 'time', lambda: clock[0])
    def sleep(seconds):
        sleeps.append(seconds)
        clock[0] += seconds
    monkeypatch.setattr(worker.time, 'sleep', sleep)
    completion = SimpleNamespace(model='test', usage=SimpleNamespace(model_dump=lambda: {'total_tokens': 200}))
    raw = SimpleNamespace(headers={'x-ratelimit-limit-tokens': '8000', 'x-ratelimit-remaining-tokens': '0'}, parse=lambda: completion)
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(with_raw_response=SimpleNamespace(create=lambda **kw: raw))))
    log = []
    path = tmp_path/'pacing.json'
    create = worker.paced_completion(client, path, log)
    assert create(model='test', messages=[]) is completion
    assert not sleeps
    assert create(model='test', messages=[]) is completion
    assert sleeps and log[1]['event'] == 'pacing'
    # Each fresh worker reads the same saved budget instead of resetting it.
    other = worker.paced_completion(client, path, log)
    assert other(model='test', messages=[]) is completion
    assert len(sleeps) == 2


def test_explicit_quota_recovery_keeps_completed_quality_failures(tmp_path):
    previous = tmp_path/'previous'
    previous.mkdir()
    versions = e.freeze_sources(previous)
    for filename in ('golden.json', 'ledger.csv'):
        (previous/filename).write_bytes(Path('evals',filename).read_bytes())
    original = {'state': 'complete', 'versions': versions,
                'dependencies': {'python': e.sys.version.split()[0]},
                'config': {'golden_sha256': e.digest(previous/'golden.json'),
                           'ledger_sha256': e.digest(previous/'ledger.csv')},
                'answers': [{'id': 'wrong', 'version': 'baseline', 'repeat': 1, 'status': 'ok', 'answer': 'wrong financial value'},
                            {'id': 'quota', 'version': 'baseline', 'repeat': 1, 'status': 'error', 'answer': 'rate_limit_exceeded'},
                            {'id': 'other', 'version': 'final', 'repeat': 1, 'status': 'max_steps', 'answer': 'step limit'}],
                'grades': {}, 'controls': {}}
    e.save_json(previous/'results.json', original)
    original_hash = e.digest(previous/'results.json')
    output = tmp_path/'recovery'
    recovered = e.recover_quota(previous, output)
    assert {a['id'] for a in recovered['answers']} == {'wrong','other'}
    assert recovered['recovery']['quota_executions_to_retry'] == 1
    assert not recovered['grades'] and not recovered['controls']
    assert recovered['versions'] == original['versions']
    assert e.digest(previous/'results.json') == original_hash
    assert e.digest(output/'previous_results.json') == original_hash
    assert (output/'sources/evaluation_transport.py').is_file()
    # A further account replacement must preserve the earlier answers' epochs.
    recovered['state'] = 'complete'
    recovered['answers'].append({'id': 'quota', 'version': 'final', 'repeat': 1,
                                'status': 'error', 'answer': 'rate_limit_exceeded',
                                'account_epoch': 'replacement_1'})
    recovered['answers'][0]['account_epoch'] = 'replacement_1'
    e.save_json(output/'results.json', recovered)
    again = e.recover_quota(output, tmp_path/'second-recovery')
    assert again['answers'][0]['account_epoch'] == 'replacement_1'
    assert again['recovery']['depth'] == 2
    assert again['recovery']['replacement_account_epoch'] == 'replacement_2'


def test_transport_retries_minute_limits_and_preserves_daily_exhaustion(monkeypatch, tmp_path):
    from finance_agent import evaluation_transport as transport
    class ApiError(Exception):
        status_code = 429
        response = SimpleNamespace(headers={'retry-after': '2'})
    sleeps, calls = [], []
    monkeypatch.setattr(transport.time, 'sleep', sleeps.append)
    completion = SimpleNamespace(model='test', usage=None)
    raw = SimpleNamespace(headers={}, parse=lambda: completion)
    def create(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise ApiError('tokens per minute')
        return raw
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(with_raw_response=SimpleNamespace(create=create))))
    log = []
    assert transport.paced_completion(client, tmp_path/'minute.json', log)(model='test') is completion
    assert len(calls) == 2 and sleeps == [2.5]
    assert log[0]['event'] == 'rate_limit_retry'
    def daily(**kwargs):
        raise ApiError('tokens per day (TPD) exhausted')
    client.chat.completions.with_raw_response.create = daily
    sleeps.clear()
    with pytest.raises(ApiError, match='per day'):
        transport.paced_completion(client, tmp_path/'daily.json', [])(model='test')
    assert not sleeps
