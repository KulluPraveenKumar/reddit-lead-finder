"""Author heuristics — ``[deleted]``, the known bots, and the ``*Bot`` suffix.

[34 §P9](../../docs/34-implementation-plan.md) task 3: *"Author heuristics:
``[deleted]``, AutoModerator, ``*Bot``, allowlist"*. Rejections report
``bot_or_deleted`` with the rule that fired in ``detail``.

The exact-match set and the suffix rule are separate on purpose, and the reason
is [AD-10b](../../docs/ARCHITECTURE_FREEZE.md): the set is provably right, and
the suffix is a heuristic that can be wrong in the direction nobody sees.
"""

from __future__ import annotations

from . import ADMITTED, BOT_OR_DELETED, RuleResult, reject

#: Authors whose posts are never leads, matched **exactly** after casefolding.
#:
#: Deliberately an exact-match set rather than a pattern.
#: ``src/discovery/triage.py`` reached the same shape independently and for the
#: same reason: these are known account names, and a name is not a heuristic.
BOT_AUTHORS = frozenset(
    {
        "automoderator",
        "autotldr",
        "remindmebot",
        "sneakpeekbot",
        "totesmessenger",
        "wikitextbot",
        "imagesofnetwork",
        "savevideo",
    }
)

#: The strings both collection paths produce for an account that is gone.
DELETED_AUTHORS = frozenset({"[deleted]", "[removed]"})

#: Separators that make a trailing "bot" unambiguous. See :func:`_looks_like_a_bot`.
_BOT_SEPARATORS = ("_bot", "-bot", ".bot")


def _looks_like_a_bot(author: str) -> bool:
    """The ``*Bot`` suffix rule, anchored so it does not eat real names.

    Three ways a name reads as a bot, and each is narrower than it first looks:

    * it ends in ``Bot`` with a **capital B** -- ``WikiTextBot``, ``MyBot``;
    * it ends in ``_bot``, ``-bot`` or ``.bot`` in any case;
    * it is in :data:`BOT_AUTHORS`, handled by the caller.

    ⚠️ **A plain lower-case ``bot`` ending is deliberately NOT a match**, and
    that is the whole design of this function. ``Abbot``, ``Talbot`` and
    ``Cabot`` are real surnames that end in the letters ``b-o-t``; a
    case-insensitive suffix rule discards those people silently, and the holdout
    audit that would surface it does not exist until P11.

    The trade is explicit: a bot named ``somebot``, all lower case with no
    separator, is **missed**. That is the correct direction to be wrong in. A
    missed bot costs one wasted analysis; a discarded human costs a lead nobody
    can see was lost, which is precisely what AD-10b is about.

    A naive ``"bot" in author`` -- mutation **M13** -- fails all of
    ``Botany_Nerd``, ``robotics_guy`` and ``Abbot``.
    """
    if author.endswith("Bot"):
        return True
    folded = author.casefold()
    return any(folded.endswith(sep) for sep in _BOT_SEPARATORS)


def check_author(
    author: str | None,
    *,
    skip_deleted_authors: bool = True,
    skip_bot_authors: bool = True,
    allowlist: frozenset[str] | set[str] | None = None,
) -> RuleResult:
    """Judge an author. Never raises; a missing author is admitted, not an error.

    ``allowlist`` wins over every rule below it, casefolded. It exists because a
    legitimate account *will* eventually trip the suffix rule, and the operator
    needs a way to say so that is not "edit the regex".

    The two flags are ``rules.skip_deleted_authors`` and
    ``rules.skip_bot_authors``. They are parameters here rather than config
    reads: this package does not touch ``config.yaml`` until Stage 4, and a pure
    function that takes its settings is testable from literals. Mutation **M12**
    is a rule that ignores ``skip_bot_authors=False``.

    A missing author is **admitted**. ``None`` means the collection path did not
    report one, which is not the same fact as ``[deleted]`` -- the same
    zero-versus-unknown distinction DI13 records for ``num_comments``, and it is
    not this module's place to collapse it.
    """
    if author is None:
        return ADMITTED
    name = author.strip()
    if not name:
        return ADMITTED

    if allowlist and name.casefold() in {a.casefold() for a in allowlist}:
        return ADMITTED

    if skip_deleted_authors and name.casefold() in {d.casefold() for d in DELETED_AUTHORS}:
        return reject(BOT_OR_DELETED, detail="deleted")

    if skip_bot_authors:
        if name.casefold() in BOT_AUTHORS:
            return reject(BOT_OR_DELETED, detail="known_bot")
        if _looks_like_a_bot(name):
            return reject(BOT_OR_DELETED, detail="bot_suffix")

    return ADMITTED
