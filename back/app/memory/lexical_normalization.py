"""Immutable PostgreSQL folding for indexed lexical candidate retrieval.

The stored projection uses built-in functions only; there is no runtime extension
or per-row normalization in the search predicate. Combining ranges follow Python
3.14 Unicode 16.0, matching relevance.fold's accent removal. Original content and
the original full-text projection remain available.
"""

from __future__ import annotations


# Code-point ranges with a nonzero canonical combining class. C collation makes
# PostgreSQL regex ranges independent of the database's linguistic collation.
_COMBINING_RANGES = (
    '\u0300-\u034e\u0350-\u036f\u0483-\u0487\u0591-\u05bd\u05bf\u05c1-\u05c2\u05c4-\u05c5\u05c7\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06dc'
    '\u06df-\u06e4\u06e7-\u06e8\u06ea-\u06ed\u0711\u0730-\u074a\u07eb-\u07f3\u07fd\u0816-\u0819\u081b-\u0823\u0825-\u0827\u0829-\u082d\u0859-\u085b'
    '\u0897-\u089f\u08ca-\u08e1\u08e3-\u08ff\u093c\u094d\u0951-\u0954\u09bc\u09cd\u09fe\u0a3c\u0a4d\u0abc'
    '\u0acd\u0b3c\u0b4d\u0bcd\u0c3c\u0c4d\u0c55-\u0c56\u0cbc\u0ccd\u0d3b-\u0d3c\u0d4d\u0dca'
    '\u0e38-\u0e3a\u0e48-\u0e4b\u0eb8-\u0eba\u0ec8-\u0ecb\u0f18-\u0f19\u0f35\u0f37\u0f39\u0f71-\u0f72\u0f74\u0f7a-\u0f7d\u0f80'
    '\u0f82-\u0f84\u0f86-\u0f87\u0fc6\u1037\u1039-\u103a\u108d\u135d-\u135f\u1714-\u1715\u1734\u17d2\u17dd\u18a9'
    '\u1939-\u193b\u1a17-\u1a18\u1a60\u1a75-\u1a7c\u1a7f\u1ab0-\u1abd\u1abf-\u1ace\u1b34\u1b44\u1b6b-\u1b73\u1baa-\u1bab\u1be6'
    '\u1bf2-\u1bf3\u1c37\u1cd0-\u1cd2\u1cd4-\u1ce0\u1ce2-\u1ce8\u1ced\u1cf4\u1cf8-\u1cf9\u1dc0-\u1dff\u20d0-\u20dc\u20e1\u20e5-\u20f0'
    '\u2cef-\u2cf1\u2d7f\u2de0-\u2dff\u302a-\u302f\u3099-\u309a\ua66f\ua674-\ua67d\ua69e-\ua69f\ua6f0-\ua6f1\ua806\ua82c\ua8c4'
    '\ua8e0-\ua8f1\ua92b-\ua92d\ua953\ua9b3\ua9c0\uaab0\uaab2-\uaab4\uaab7-\uaab8\uaabe-\uaabf\uaac1\uaaf6\uabed'
    '\ufb1e\ufe20-\ufe2f\U000101fd\U000102e0\U00010376-\U0001037a\U00010a0d\U00010a0f\U00010a38-\U00010a3a\U00010a3f\U00010ae5-\U00010ae6\U00010d24-\U00010d27\U00010d69-\U00010d6d'
    '\U00010eab-\U00010eac\U00010efd-\U00010eff\U00010f46-\U00010f50\U00010f82-\U00010f85\U00011046\U00011070\U0001107f\U000110b9-\U000110ba\U00011100-\U00011102\U00011133-\U00011134\U00011173\U000111c0'
    '\U000111ca\U00011235-\U00011236\U000112e9-\U000112ea\U0001133b-\U0001133c\U0001134d\U00011366-\U0001136c\U00011370-\U00011374\U000113ce-\U000113d0\U00011442\U00011446\U0001145e\U000114c2-\U000114c3'
    '\U000115bf-\U000115c0\U0001163f\U000116b6-\U000116b7\U0001172b\U00011839-\U0001183a\U0001193d-\U0001193e\U00011943\U000119e0\U00011a34\U00011a47\U00011a99\U00011c3f'
    '\U00011d42\U00011d44-\U00011d45\U00011d97\U00011f41-\U00011f42\U0001612f\U00016af0-\U00016af4\U00016b30-\U00016b36\U00016ff0-\U00016ff1\U0001bc9e\U0001d165-\U0001d169\U0001d16d-\U0001d172\U0001d17b-\U0001d182'
    '\U0001d185-\U0001d18b\U0001d1aa-\U0001d1ad\U0001d242-\U0001d244\U0001e000-\U0001e006\U0001e008-\U0001e018\U0001e01b-\U0001e021\U0001e023-\U0001e024\U0001e026-\U0001e02a\U0001e08f\U0001e130-\U0001e136\U0001e2ae\U0001e2ec-\U0001e2ef'
    '\U0001e4ec-\U0001e4ef\U0001e5ee-\U0001e5ef\U0001e8d0-\U0001e8d6\U0001e944-\U0001e94a'
)


def folded_sql(expression: str) -> str:
    """Fold a trusted SQL expression, never an interpolated user value.

    NFKD expands compatibility forms; lower plus the two remaining common
    case-fold differences preserves sharp-s and Greek final-sigma searches.
    Query values use relevance.fold and are always passed as SQL parameters.
    """
    return f"""replace(replace(regexp_replace(normalize(lower({expression}), NFKD) COLLATE "C", '[{_COMBINING_RANGES}]', '', 'g'), 'ß', 'ss'), 'ς', 'σ')"""


def folded_vector_sql() -> str:
    """Use the same title/keyword/body weights as the original FTS projection."""
    return " || ".join(
        "setweight(to_tsvector('simple'::regconfig, " + folded_sql(value) + "), '" + weight + "')"
        for value, weight in (
            ("coalesce(title, '')", "A"),
            ("coalesce(keywords::text, '')", "B"),
            ("coalesce(search_text, '')", "C"),
        )
    )
