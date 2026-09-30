"""Shared Groq/OpenAI transport pacing for evaluation calls only."""
import json
import re
import time


def duration(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        units = {'ms': .001, 's': 1, 'm': 60, 'h': 3600}
        return sum(float(n) * units[u] for n, u in re.findall(r'(\d+(?:\.\d+)?)(ms|s|m|h)', value or ''))


def paced_completion(client, path, log):
    """Same transport policy for both versions; shared header-driven token pacing."""
    raw_create = client.chat.completions.with_raw_response.create
    def wait(seconds):
        while seconds > 0:
            chunk = min(seconds, 30)
            print(f'    RATE PACING: waiting {seconds:.1f}s for Groq token budget', flush=True)
            time.sleep(chunk)
            seconds -= chunk
    def create(**kwargs):
        state = json.loads(path.read_text()) if path.exists() else {}
        state = state.get(kwargs['model'], {})
        limit = state.get('limit', 8000)
        available = min(limit, state.get('remaining', limit) + max(0, time.time()-state.get('at', 0))*limit/60)
        estimated = min(len(json.dumps(kwargs))/3 + 512, limit*.9)
        delay = max(0, (estimated-available)*60/limit)
        if delay:
            log.append({'event': 'pacing', 'seconds': delay})
            wait(delay + .5)
        for attempt in range(4):
            try:
                raw = raw_create(**kwargs)
                completion = raw.parse()
                headers = raw.headers
                states = json.loads(path.read_text()) if path.exists() else {}
                states[kwargs['model']] = {'limit': float(headers.get('x-ratelimit-limit-tokens', 8000)),
                                          'remaining': float(headers.get('x-ratelimit-remaining-tokens', 0)),
                                          'at': time.time()}
                temporary = path.with_suffix('.tmp')
                temporary.write_text(json.dumps(states))
                temporary.replace(path)
                log.append({'event': 'completion', 'model': completion.model,
                            'usage': completion.usage.model_dump() if completion.usage else None,
                            'remaining_tpm_tokens': states[kwargs['model']]['remaining']})
                return completion
            except Exception as exc:
                if getattr(exc, "status_code", None) != 429:
                    raise
                # Daily quota exhaustion is permanent for this run; preserve it as an execution error.
                if attempt == 3 or 'per day' in str(exc).lower() or '(TPD)' in str(exc):
                    raise
                retry = max(1, duration(exc.response.headers.get('retry-after')),
                            duration(exc.response.headers.get('x-ratelimit-reset-tokens')))
                log.append({'event': 'rate_limit_retry', 'attempt': attempt+1, 'seconds': retry})
                wait(retry + .5)
    return create

