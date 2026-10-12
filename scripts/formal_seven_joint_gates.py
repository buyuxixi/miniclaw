"""Fit consumers in conflict-first order using predictions, never hidden gold masks."""
from copy import deepcopy
import json
from scripts.formal_seven_label_gates import fit_labels, apply_labels
from scripts.formal_seven_consumption_gates import consumed
from miniclaw_web.formal_confirmations import confirmation_profile


def blocked(prediction):
    return (prediction.get('selective_acceptance', {}).get('conflict', False)
            and prediction['answers']['conflict']['choice'] == 'present')


def fit_joint(samples):
    gates = fit_labels(samples)
    gates.update(version='formal-seven-joint-v1', version_projection='opaque-sha256-to-null-v1')
    gates['rule'] += '; accepted conflict suspends intent/target/scope/role; then fit actual executing consumers'
    active = [r for r in samples if not blocked(apply_labels(r['prediction'], gates))]
    gates['questions']['intent'] = fit_labels(active)['questions']['intent'] if active else dict(enabled=False, labels={})
    gates['questions']['intent']['consumer_records'] = len(active)
    for head in ('target', 'scope', 'reference_role'):
        subset = [r for r in active if consumed(head, json.loads(r['request'][0]), apply_labels(r['prediction'], gates))]
        fitted = fit_labels(subset)['questions'][head] if subset else dict(enabled=False, labels={})
        fitted.update(consumer_records=len(subset), consumer_families=len({r['family'] for r in subset}))
        gates['questions'][head] = fitted
    return gates


def apply_joint(row, gates, request):
    result = apply_labels(row, gates)
    state = json.loads(request[0])
    for head in ('intent', 'target', 'scope', 'reference_role'):
        if blocked(result) or (head != 'intent' and not consumed(head, state, result)):
            result['answers'][head]['confidence'] = 0.
            result['selective_acceptance'][head] = False
    return result


def inference_request(request, gates):
    """Opaque host revision is not semantic content; caller retains it for validation/cache."""
    state = json.loads(request[0])
    version = state['target_versions']
    if version is not None:
        if (gates.get('version_projection') != 'opaque-sha256-to-null-v1'
                or not isinstance(version, str) or len(version) != 64
                or any(c not in '0123456789abcdef' for c in version)):
            raise ValueError('unsupported_host_version')
        state['target_versions'] = None
    if gates.get('version')=='formal-seven-joint-v2':
        if confirmation_profile(state) not in gates.get('confirmation_profiles',[]):
            raise ValueError('confirmation_profile_outside_calibration')
    elif state['confirmed']:raise ValueError('candidate_state_outside_calibration')
    if len(state['candidates']) not in gates.get('candidate_counts', []):
        raise ValueError('candidate_state_outside_calibration')
    return (json.dumps(state, ensure_ascii=False), deepcopy(request[1]))
