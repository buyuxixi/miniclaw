"""Compatibility fix for the pinned upstream's moved Skills prompt tier."""
def attribute_skills(payload, parts):
    from agent.context_breakdown import _chars_to_tokens, _skills_block
    stable = parts.get('stable', '') or ''
    volatile = parts.get('volatile', '') or ''
    # This upstream computes the Skills category from stable only, while its
    # prompt builder puts the live index in volatile. Move the estimate out of
    # system_prompt; never change provider usage or inject new model content.
    index = _skills_block(volatile)
    if not index or _skills_block(stable):
        return payload
    count = _chars_to_tokens(index)
    categories = [dict(c) for c in payload['categories']]
    system = next((c for c in categories if c['id'] == 'system_prompt'), None)
    if system is None:
        return payload
    count = min(count, system['tokens'])
    system['tokens'] -= count
    categories.append(dict(id='skills', label='Skills', color='var(--context-usage-skills)', tokens=count))
    return {**payload, 'categories': [c for c in categories if c['tokens'] > 0]}


def install_attribution_fix():
    from agent import context_breakdown
    from agent.system_prompt import build_system_prompt_parts
    original = context_breakdown.compute_session_context_breakdown
    if getattr(original, '_miniclaw_fix', False):
        return
    def corrected(agent, messages=None):
        return attribute_skills(original(agent, messages), build_system_prompt_parts(agent))
    corrected._miniclaw_fix = True
    context_breakdown.compute_session_context_breakdown = corrected
