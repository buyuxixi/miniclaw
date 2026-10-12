"""Use the app-wide primary/fallback service, with an optional chat override."""
import os
from .clarification_policy import ClarificationPolicy


def chat_policy(default_decisions, environ=None):
    env = os.environ if environ is None else environ
    from .decision_routing import RoutedDecisions, local_decisions
    provider = env.get('MINICLAW_CHAT_DECISION_PROVIDER', 'inherit')
    if provider == 'inherit':
        if isinstance(default_decisions, RoutedDecisions):
            from .candidate_clarification_policy import CandidateClarificationPolicy
            return CandidateClarificationPolicy(default_decisions)
        return ClarificationPolicy(default_decisions)
    if provider == 'jev':
        return ClarificationPolicy(default_decisions.fallback if isinstance(default_decisions, RoutedDecisions) else default_decisions)
    if provider != 'laya':
        raise ValueError('unsupported_chat_decision_provider')
    from .candidate_clarification_policy import CandidateClarificationPolicy
    # Production always supplies a durable service. Keep pure providers only in
    # explicitly constructed offline comparison policies, not in this factory.
    if isinstance(default_decisions, RoutedDecisions):
        return CandidateClarificationPolicy(default_decisions)
    from .decisions import JevDecisions
    if isinstance(default_decisions, JevDecisions):
        try:
            primary = local_decisions(env)
        except (ValueError, TypeError):
            primary = None
        return CandidateClarificationPolicy(RoutedDecisions(default_decisions.store, primary, default_decisions))
    # Test doubles/custom integrations have no durable store or cloud ledger.
    return CandidateClarificationPolicy(local_decisions(env))
