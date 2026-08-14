"""Rules — the deterministic filter. Every rejection here costs nothing.

P9 gives this package five modules: keyword tiers and negative terms
(``keywords``), structural noise regexes (``structural``), author heuristics
(``authors``), and competitor matching behind an interface whose implementation
does not arrive until P15 (``competitors``).

**This file is deliberately empty of logic.** Stage 1 of P9 creates the package
so that the R3 fence has something to walk, and the fence lands *before* the
modules it constrains -- the same ordering P8 used for its foreign-key guard,
which ``docs/progress/P08-COMPLETE.md`` §2 calls that phase's real product. The
types and the rules arrive in Stage 2.

One boundary holds from the first file, because retrofitting it is far more
expensive than starting with it:

* **No AI, ever.** ``ARCHITECTURE_FREEZE`` **R3** names this package first:
  ``rules/``, ``dedupe/``, ``scoring/``, ``knowledge/``, ``feedback/`` and
  ``discovery/policy.py`` never import ``src.ai``. That rule carries
  ``docs/06c`` §2's entire cost argument -- if the code built to avoid paying a
  model could call one, it would be the thing doing the paying.

  The shortest path to breaking it is real and specific: ``src/ai/gate.py``
  already ships ``PreAIGate``, whose rule plugins return a ``GateDecision``. A
  rule here that returned one would have to import it. **It must not.** This
  package owns its own neutral result type (Stage 2), and the adapter that turns
  it into a ``GateDecision`` lives on the ``src.ai`` side of the boundary, where
  the import is legal -- which is P19's, not P9's.

  ``tests/test_boundaries.py`` asserts this from now, and asserts that this
  package exists, so deleting it fails a test rather than quietly reducing the
  fence to a no-op over an empty directory.
"""

__all__: list[str] = []
