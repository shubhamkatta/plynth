"""Property-based tests for `app.services.rbac._matches`.

The wildcard matcher is the heart of RBAC — every authenticated mutation
flows through `user_has_permission` which fans out to `_matches(granted,
required)`. A regression here silently widens or narrows every permission
in the system, so we hammer the invariants directly with Hypothesis.

Conventions:
- Pure unit tests, no DB, no fixtures.
- `_matches` splits on the first `:`, so we generate `resource` and
  `action` as separate strings and assemble the codes locally — this
  matches how `SYSTEM_PERMISSIONS` are spelled (`resource:action`).
- The codebase uses lower-case ASCII codes; we restrict the alphabet to
  lowercase letters to avoid pulling in `:` characters (which would
  change the split) and to keep examples readable in shrink output.
"""

import hypothesis
from hypothesis import given, settings
from hypothesis import strategies as st

from app.services.rbac import _matches

# Lowercase ASCII letters only — matches the spelling convention of
# `SYSTEM_PERMISSIONS` and avoids `:` (which is the separator) or
# `*` (which is the wildcard sigil).
segment = st.text(
    alphabet=st.characters(whitelist_categories=("Ll",)),
    min_size=1,
    max_size=12,
)


@given(resource=segment, action=segment)
@settings(max_examples=200, deadline=None)
def test_full_wildcard_matches_everything(resource: str, action: str) -> None:
    # Why this property? `*:*` is the owner-role permission; if it ever
    # stops matching an arbitrary `resource:action`, owners are locked out.
    assert _matches("*:*", f"{resource}:{action}") is True


@given(resource=segment, action1=segment, action2=segment)
@settings(max_examples=200, deadline=None)
def test_resource_wildcard_matches_any_action_on_that_resource(
    resource: str, action1: str, action2: str
) -> None:
    # Why this property? `users:*` is the standard "full control over
    # users" grant. It must cover every action on `users`, including ones
    # we haven't invented yet.
    code = f"{resource}:*"
    assert _matches(code, f"{resource}:{action1}") is True
    assert _matches(code, f"{resource}:{action2}") is True


@given(resource1=segment, resource2=segment, action=segment)
@settings(max_examples=200, deadline=None)
def test_action_wildcard_matches_that_action_across_resources(
    resource1: str, resource2: str, action: str
) -> None:
    # Why this property? `*:read` would mean "read anything" — symmetric
    # to the resource wildcard. Not used in default SYSTEM_PERMISSIONS
    # but documented as supported, so we lock the semantics in.
    code = f"*:{action}"
    assert _matches(code, f"{resource1}:{action}") is True
    assert _matches(code, f"{resource2}:{action}") is True


@given(r=segment, a=segment, r2=segment, a2=segment)
@settings(max_examples=200, deadline=None)
def test_non_wildcard_grant_only_matches_itself(
    r: str, a: str, r2: str, a2: str
) -> None:
    # Why this property? A concrete grant like `users:read` must NEVER
    # accidentally permit `users:write` or `billing:read`. This is the
    # least-privilege guarantee — a bug here is a silent privilege
    # escalation.
    granted = f"{r}:{a}"
    required = f"{r2}:{a2}"
    expected = (r == r2) and (a == a2)
    assert _matches(granted, required) is expected


@given(resource=segment, action=segment)
@settings(max_examples=200, deadline=None)
def test_reflexive_on_concrete_codes(resource: str, action: str) -> None:
    # Why this property? `_matches(x, x)` must always hold — the trivial
    # case of "you have exactly what's required". A break here would
    # mean every concrete permission stops working.
    code = f"{resource}:{action}"
    assert _matches(code, code) is True


@given(r1=segment, a1=segment, r2=segment, a2=segment)
@settings(max_examples=200, deadline=None)
def test_resource_mismatch_with_concrete_action_never_matches(
    r1: str, a1: str, r2: str, a2: str
) -> None:
    # Why this property? Resource boundaries are absolute: a `tenants:*`
    # grant must never satisfy a `users:read` requirement. We constrain
    # this only when the resources actually differ.
    hypothesis.assume(r1 != r2)
    # Both concrete: differing resource → no match regardless of action.
    assert _matches(f"{r1}:{a1}", f"{r2}:{a2}") is False
    # Resource-wildcarded grant on r1 must not satisfy requirement on r2.
    assert _matches(f"{r1}:*", f"{r2}:{a2}") is False
