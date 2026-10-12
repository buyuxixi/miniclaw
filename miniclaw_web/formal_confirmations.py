"""Bounded primary input profiles; these describe saved answers, not permission proofs."""
def confirmation_profile(state):
    confirmed=state['confirmed']
    if not isinstance(confirmed,dict):raise ValueError('invalid_confirmations')
    if not confirmed:return 'none'
    if set(confirmed)=={'Q_EXECUTION'}:
        if confirmed['Q_EXECUTION'] in ('确认执行','确认生成'):return 'execute'
        if confirmed['Q_EXECUTION']=='只整理方案':return 'draft'
    if set(confirmed)=={'Q_TARGET','target_id'}:
        cs=state['candidates'];target=confirmed['target_id'];answer=confirmed['Q_TARGET']
        if not isinstance(target,str) or not isinstance(answer,str) or not 1<=len(answer)<=100:raise ValueError('invalid_target_confirmation')
        matches=[c for c in cs if answer in (c['id'],c['label'])]
        if len(matches)==1 and matches[0]['id']==target and state['selected']==target:return 'target'
    raise ValueError('confirmation_profile_outside_calibration')
