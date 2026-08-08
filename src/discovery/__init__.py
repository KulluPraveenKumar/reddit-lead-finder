"""Discovery — how posts are found, as opposed to how they are fetched or judged.

P5 gives this package one file: the Atom parser behind ``RedditClient.get_feed``.
P6 adds watermarks, the incremental diff and the polling policy beside it.

Two boundaries hold from the first file, because retrofitting either is far more
expensive than starting with it:

* **No AI.** Discovery decides *what to look at*, never *what it is worth*. P6
  makes ``grep -rn "import.*src\\.ai" src/discovery/`` returning nothing an
  acceptance criterion; ``tests/test_boundaries.py`` asserts it from now.
* **No transport.** The parser takes bytes and returns dicts. It holds no
  client, no session and no config, which is what lets it be tested against
  fixtures with no network at all.
"""

from .feed_parser import FeedParseError, parse_feed

__all__ = ["FeedParseError", "parse_feed"]
