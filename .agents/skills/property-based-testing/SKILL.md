---
name: property-based-testing
description: Write, review, or diagnose property-based tests with Hypothesis or fast-check for invariants, parsers, serializers, validators, and normalization. Use when generated input domains add value beyond example tests; not for browser journeys or performance measurements.
---
# Property-Based Testing

## Galaris integration

Use the repository's existing test stack and synthetic fixtures. Run backend tests with
`make tests ARGS='path/to/test.py'` against the ephemeral database; never run pytest in the
development backend. Follow `general` for dependency changes and container execution.
Choose a property grounded in the contract, such as serialization roundtrips or normalization
idempotence. Keep DB workflow guarantees in integration tests; pure generators do not prove
transaction or concurrency behavior. A property test does not justify an unrelated refactor.

An example test asserts one point. A property asserts a rule over the whole input
domain and lets the generator hunt for the counterexample. That trade is worth making
when the code has an algebraic shape — an inverse, an invariant, an oracle — and not
otherwise. Code with no such shape gets example tests; saying so is a valid outcome.

When refactoring for testability is within scope, consult
[references/refactoring.md](references/refactoring.md) for ways to expose a useful property.
Otherwise prefer an existing seam or an example test that proves the required behavior.

## Property catalog

| Property | Formula | Where it applies |
|---|---|---|
| Roundtrip | `decode(encode(x)) == x` | Serialization, conversion pairs |
| Inverse | `f(g(x)) == x` | encrypt/decrypt, compress/decompress |
| Oracle | `new(x) == reference(x)` | Optimization, refactoring, reimplementation |
| Idempotence | `f(f(x)) == f(x)` | Normalization, formatting, sorting |
| Invariant | Holds before and after | Any transformation, contract state |
| Easy to verify | `is_sorted(sort(x))` | Complex algorithms with cheap checkers |
| Commutativity | `f(a, b) == f(b, a)` | Binary and set operations |
| Associativity | `f(f(a,b), c) == f(a, f(b,c))` | Combining operations |
| Identity | `f(x, e) == x` | Operations with a neutral element |

Strength ordering, weakest to strongest:
`no crash → type preservation → invariant → idempotence → roundtrip / oracle`.

Assert the strongest property the code supports. "No crash" alone rarely justifies the
dependency. If no meaningful invariant is available within the task's scope, explain why
example tests are a better fit.

## The two ways a property test asserts nothing

- **Tautology.** `assert add(a, b) == a + b` restates the implementation; no bug they
  share can fail it. Pick a property that constrains the function without recomputing
  it. Note the exception: `f(x) == f(x)` is a genuine determinism property when `f`
  is not obviously pure — serializers over dicts or sets, hashing, anything reading
  the clock.
- **Vacuity.** `assume()` that filters out nearly every input passes without
  exercising anything, and self-contradictory `assume()` passes having run zero cases.
  Push constraints into the strategy so the generator produces valid inputs directly.

## Where to look next

Load the one that matches the task in front of you:

| Task | File |
|---|---|
| Writing new tests, designing strategies | [references/generating.md](references/generating.md) |
| The code has no property to assert yet | [references/refactoring.md](references/refactoring.md) |
| Reviewing existing property tests | [references/reviewing.md](references/reviewing.md) |
| A property test just failed | [references/interpreting-failures.md](references/interpreting-failures.md) |
| Library choice, Echidna and Medusa | [references/libraries.md](references/libraries.md) |

## Introducing PBT to a project that lacks it

Reuse an existing PBT library. If a new dependency is needed, justify it with a concrete
property and follow the repository's dependency workflow within the user's authorized scope.
Installing this skill alone does not install or require a test library.

## Provenance

See [SOURCE.md](SOURCE.md) for the pinned upstream revision, license, and local changes.
