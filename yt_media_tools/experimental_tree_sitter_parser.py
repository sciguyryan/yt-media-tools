"""Optional Tree-sitter boundary for the yt-sql parser experiment.

The generated language package and Tree-sitter runtime are deliberately absent
from the production dependency set. This module must therefore remain safe to
import when neither optional package is installed.
"""

from __future__ import annotations

from functools import lru_cache
from importlib.util import find_spec
import re

from .experimental_tree_sitter_model_builder import TreeSitterModelBuilder
from .query_model import QueryLexicalError, QuerySyntaxError

TREE_SITTER_ABI = 15
TREE_SITTER_RUNTIME_VERSION = "0.26.0"
_BASE_INTEGER_TOKEN = re.compile(r"(?<![\w.])[+-]?0(?P<prefix>[xXoObB])(?P<digits>[0-9A-Za-z_]*)")
_BASE_DIGITS = {
    "x": re.compile(r"[0-9a-fA-F]+(?:_[0-9a-fA-F]+)*"),
    "o": re.compile(r"[0-7]+(?:_[0-7]+)*"),
    "b": re.compile(r"[01]+(?:_[01]+)*"),
}
_BASE_DIGIT_CHARACTERS = {
    "x": frozenset("0123456789abcdefABCDEF_"),
    "o": frozenset("01234567_"),
    "b": frozenset("01_"),
}


class TreeSitterUnavailableError(RuntimeError):
    """Raised when the optional experimental parser has not been installed."""


def tree_sitter_available() -> bool:
    """Return whether both optional Tree-sitter packages are installed."""
    return find_spec("tree_sitter") is not None and find_spec("tree_sitter_yt_sql") is not None


@lru_cache(maxsize=1)
def _parser():
    """Construct the optional parser once for experimental measurements."""
    try:
        from tree_sitter import Language, Parser
        import tree_sitter_yt_sql
    except ImportError as error:
        raise TreeSitterUnavailableError(
            "The experimental Tree-sitter runtime and yt-sql language package are not installed."
        ) from error

    language = Language(tree_sitter_yt_sql.language())
    if language.abi_version != TREE_SITTER_ABI:
        raise TreeSitterUnavailableError(
            f"The experimental yt-sql grammar uses Tree-sitter ABI {language.abi_version}; "
            f"ABI {TREE_SITTER_ABI} is required."
        )
    return Parser(language)


def _parse_tree_sitter_tree(source: str):
    """Parse UTF-8 source without exposing the concrete tree as a public API."""
    return _parser().parse(source.encode("utf-8"))


def _character_offset(source_bytes: bytes, byte_offset: int) -> int:
    """Convert one Tree-sitter UTF-8 byte offset to a Python character offset."""
    return len(source_bytes[:byte_offset].decode("utf-8", errors="ignore"))


def _masked_source(source: str) -> str:
    """Blank quoted and commented text while retaining source offsets.

    Diagnostic translation needs to inspect clause boundaries without treating
    keywords inside values, quoted identifiers or comments as syntax. Lexical
    failures are raised here because Tree-sitter recovery cannot reliably
    distinguish an unterminated token from a missing grammatical construct.
    """
    masked = list(source)
    index = 0
    while index < len(source):
        character = source[index]
        if character == "#":
            end = index
            while end < len(source) and source[end] not in "\r\n":
                masked[end] = " "
                end += 1
            index = end
            continue
        if character not in {"'", '"', "`"}:
            index += 1
            continue

        quote = character
        start = index
        index += 1
        while index < len(source):
            if quote != "`" and source[index] == "\\":
                masked[index] = " "
                if index + 1 < len(source):
                    masked[index + 1] = " "
                    index += 2
                    continue
                raise QueryLexicalError(
                    source,
                    "Incomplete escape sequence at end of string literal.",
                    index,
                )
            if source[index] == quote:
                if index + 1 < len(source) and source[index + 1] == quote:
                    masked[index] = masked[index + 1] = " "
                    index += 2
                    continue
                end = index + 1
                if quote == "`" and end == start + 2:
                    raise QueryLexicalError(
                        source,
                        "Quoted identifier cannot be empty.",
                        start,
                        end_position=end,
                    )
                for position in range(start, end):
                    masked[position] = " "
                index = end
                break
            masked[index] = " "
            index += 1
        else:
            message = "Unterminated quoted identifier." if quote == "`" else "Unterminated string literal."
            reason = "invalid" if quote == "`" else "unterminated-string"
            raise QueryLexicalError(source, message, start, end_position=len(source), reason=reason)
    return "".join(masked)


def _validate_numeric_tokens(source: str, masked: str) -> None:
    """Reject malformed non-decimal integers before grammar recovery obscures them."""
    for match in _BASE_INTEGER_TOKEN.finditer(masked):
        prefix = match.group("prefix").casefold()
        digits = match.group("digits")
        if _BASE_DIGITS[prefix].fullmatch(digits) is None:
            base = {"x": 16, "o": 8, "b": 2}[prefix]
            raise QueryLexicalError(
                source,
                f"Invalid base-{base} integer literal {match.group(0)!r}.",
                match.start(),
            )


def _may_contain_malformed_numeric(source: str) -> bool:
    """Return whether raw text warrants quote-aware numeric validation."""
    folded = source.casefold()
    if "0x" not in folded and "0o" not in folded and "0b" not in folded:
        return False
    index = source.find("0")
    while index >= 0 and index + 1 < len(source):
        prefix = source[index + 1].casefold()
        if prefix in _BASE_DIGIT_CHARACTERS and (
            index == 0 or not (source[index - 1].isalnum() or source[index - 1] in "_.")
        ):
            end = index + 2
            while end < len(source) and (source[end].isalnum() or source[end] == "_"):
                end += 1
            digits = source[index + 2 : end]
            valid_characters = _BASE_DIGIT_CHARACTERS[prefix]
            if (
                not digits
                or digits.startswith("_")
                or digits.endswith("_")
                or "__" in digits
                or any(character not in valid_characters for character in digits)
            ):
                return True
            index = source.find("0", end)
            continue
        index = source.find("0", index + 1)
    return False


def _validate_source_characters(source: str, masked: str) -> None:
    """Reject characters outside the yt-sql lexical alphabet."""
    punctuation = frozenset("<>!=()[].@,*+-/%:")
    for position, character in enumerate(masked):
        if character.isspace() or character.isascii() and (character.isalnum() or character in punctuation | {"_"}):
            continue
        if character == "_" or character.isidentifier() or ("A" + character).isidentifier():
            continue
        raise QueryLexicalError(
            source,
            f"Unexpected character {character!r}.",
            position,
            end_position=position + 1,
        )


def _invalid_row_count_position(masked: str) -> int | None:
    """Locate an invalid LIMIT or OFFSET value using the established boundary."""
    match = re.search(r"(?i)\b(?P<clause>LIMIT|OFFSET)\s+(?P<value>\S+)", masked)
    if match is None:
        return None
    value = match.group("value")
    compact = value.replace("_", "")
    valid = re.fullmatch(r"\d+", compact)
    if valid is None:
        valid = re.fullmatch(r"0[xX][0-9a-fA-F]+|0[oO][0-7]+|0[bB][01]+", compact)
    if valid is None:
        return match.start("value")
    number = int(compact, 0) if compact.lower().startswith(("0x", "0o", "0b")) else int(compact)
    if match.group("clause").upper() == "LIMIT" and number == 0:
        return match.start("value")
    return None


def _glued_select_failure(masked: str) -> int | None:
    """Locate the reference parser's first token after a glued SELECT prefix."""
    match = re.search(r"(?i)SELECT(?=\S)", masked)
    if match is None:
        match = re.search(r"(?i)(?<=ALL)SELECT(?=\s)", masked)
    if match is None:
        return None
    tail = masked[match.end() :]
    function = re.match(r"[^\s,(]+\(", tail)
    if function is not None:
        token_start = match.start()
        while token_start > 0 and (masked[token_start - 1].isalnum() or masked[token_start - 1] in "_-"):
            token_start -= 1
        return token_start
    boundary = re.search(r"[\s,]", tail)
    if boundary is None:
        return len(masked)
    position = match.end() + boundary.start()
    if masked[position] == ",":
        return position
    while position < len(masked) and masked[position].isspace():
        position += 1
    return position


def _out_of_order_clause(masked: str) -> int | None:
    """Return the first repeated or backwards statement clause, if present."""
    pattern = re.compile(r"(?i)\bWHERE\b|\bGROUP\s+BY\b|\bHAVING\b|\bORDER\s+BY\b|\bLIMIT\b|\bOFFSET\b")
    ranks = {"WHERE": 0, "GROUP BY": 1, "HAVING": 2, "ORDER BY": 3, "LIMIT": 4, "OFFSET": 5}
    clauses = []
    depth = 0
    next_clause = iter(pattern.finditer(masked))
    match = next(next_clause, None)
    for index, character in enumerate(masked):
        while match is not None and match.start() == index:
            name = " ".join(match.group(0).upper().split())
            clauses.append((match.start(), depth, ranks[name]))
            match = next(next_clause, None)
        if character == "(":
            depth += 1
        elif character == ")":
            depth = max(0, depth - 1)

    highest_by_depth: dict[int, int] = {}
    for position, depth, rank in clauses:
        highest = highest_by_depth.get(depth, -1)
        if rank <= highest:
            return position
        highest_by_depth[depth] = rank
    return None


def _translated_tree_sitter_error(source: str, failure) -> QuerySyntaxError:
    """Translate one recovery node into stable yt-sql diagnostic vocabulary."""
    source_bytes = source.encode("utf-8")
    position = _character_offset(source_bytes, failure.start_byte)
    end_position = _character_offset(source_bytes, failure.end_byte)
    masked = _masked_source(source)
    _validate_source_characters(source, masked)
    _validate_numeric_tokens(source, masked)
    stripped = masked.rstrip()

    missing_distinct_from = re.search(
        r"(?i)\bIS\s+(?:NOT\s+)?DISTINCT\s+(?P<term>FROM[\w-]+)",
        masked,
    )
    if missing_distinct_from:
        return QuerySyntaxError(
            source,
            "Expected FROM after IS DISTINCT.",
            missing_distinct_from.start("term"),
            end_position=missing_distinct_from.end("term"),
            expected=("FROM",),
        )

    invalid_row_count = _invalid_row_count_position(masked)
    if invalid_row_count is not None:
        return QuerySyntaxError(
            source,
            "LIMIT or OFFSET requires an integer in its permitted range.",
            invalid_row_count,
        )

    malformed_order = re.search(r"(?i)\bORDER\s+(?!BY(?:\s|$))(?P<term>[^\s,()]+)", masked)
    if malformed_order:
        return QuerySyntaxError(
            source,
            "Expected BY after ORDER.",
            malformed_order.start("term"),
            end_position=malformed_order.end("term"),
            expected=("BY",),
        )

    missing_separator = re.search(r"(?i)\bWHERE(?=\S)|\bUNIONALL\b", masked)
    if missing_separator:
        return QuerySyntaxError(
            source,
            "A separator is required after the clause keyword.",
            missing_separator.start(),
            reason="missing-clause-separator",
        )

    if re.match(r"(?is)^\s*SELECT\s+FROM\s+", masked):
        relation = masked.find("@", masked.upper().find("FROM"))
        if relation >= 0:
            return QuerySyntaxError(
                source,
                "A clause separator is required.",
                relation,
                reason="missing-clause-separator",
            )

    if re.fullmatch(r"(?is)\s*SELECT\s*", masked):
        return QuerySyntaxError(source, "SELECT requires a projection.", len(source))

    duplicate = masked.find(",,")
    if duplicate >= 0:
        reason = "missing-facet" if re.search(r"(?i)\bOF\b[^)]*$", masked[: duplicate + 1]) else "invalid"
        message = "A facet name is required." if reason == "missing-facet" else "Expected a value."
        return QuerySyntaxError(source, message, duplicate + 1, reason=reason)

    if "[]" in masked:
        bracket = masked.index("[]")
        return QuerySyntaxError(
            source,
            "Collection indexing requires an index expression.",
            bracket,
            reason="missing-index-expression",
        )

    empty_query = re.search(r"(?i)\bAS\s*\(\s*(?P<close>\))", masked)
    if empty_query:
        return QuerySyntaxError(
            source,
            "Query body cannot be empty.",
            empty_query.start("close"),
            reason="empty-query",
        )

    if masked.count("(") > masked.count(")"):
        return QuerySyntaxError(
            source,
            "A closing ')' delimiter is required.",
            len(source),
            expected=(")",),
        )
    if masked.count("[") > masked.count("]"):
        return QuerySyntaxError(
            source,
            "A closing ']' delimiter is required.",
            len(source),
            expected=("]",),
        )

    glued_select = _glued_select_failure(masked)
    if glued_select is not None:
        return QuerySyntaxError(source, "The query is not valid yt-sql syntax.", glued_select)

    clause = _out_of_order_clause(masked)
    if clause is not None:
        return QuerySyntaxError(
            source,
            "A clause is repeated or out of canonical order.",
            clause,
            reason="clause-order",
        )

    if re.search(r"(?i)\b(?:FROM|JOIN)\s*$", stripped):
        return QuerySyntaxError(source, "A relation source is required.", len(source), reason="missing-source")
    if re.search(r"(?i)\bOF\s*$", stripped):
        return QuerySyntaxError(
            source,
            "A facet name is required after OF.",
            len(source),
            reason="missing-facet",
        )
    union = re.search(r"(?i)\bUNION\s*$", stripped)
    if union:
        return QuerySyntaxError(
            source,
            "UNION requires a query on both sides.",
            union.start(),
            reason="incomplete-union",
        )
    joins = tuple(re.finditer(r"(?i)\bJOIN\b", stripped))
    if joins and not re.search(r"(?i)\bON\b[^)]*$", stripped[joins[-1].end() :]):
        return QuerySyntaxError(
            source,
            "JOIN requires an ON predicate.",
            len(source),
            expected=("ON",),
            reason="missing-join-on",
        )

    if failure.is_missing and failure.type in {")", "]"}:
        return QuerySyntaxError(
            source,
            f"A closing {failure.type!r} delimiter is required.",
            position,
            expected=(failure.type,),
        )

    return QuerySyntaxError(
        source,
        "The query is not valid yt-sql syntax.",
        position,
        end_position=end_position,
    )


def _first_error_node(root):
    """Return the earliest recovery or missing node in source order."""
    pending = [root]
    failures = []
    while pending:
        node = pending.pop()
        if node.is_error or node.is_missing:
            failures.append(node)
        pending.extend(reversed(node.children))
    return min(failures, key=lambda node: (node.start_byte, node.end_byte), default=root)


def recognise_tree_sitter_query(source: str) -> None:
    """Recognise the current experimental grammar and reject recovered trees."""
    _validated_tree_sitter_tree(source)
    return None


def _validated_tree_sitter_tree(source: str, source_bytes: bytes | None = None):
    """Return one recovery-free private concrete syntax tree."""
    if _may_contain_malformed_numeric(source):
        _validate_numeric_tokens(source, _masked_source(source))
    source_bytes = source.encode("utf-8") if source_bytes is None else source_bytes
    tree = _parser().parse(source_bytes)
    root = tree.root_node
    if root.has_error:
        failure = _first_error_node(root)
        raise _translated_tree_sitter_error(source, failure)
    return tree


def parse_tree_sitter_query(source: str):
    """Parse yt-sql into the existing model through the optional Tree-sitter CST."""
    source_bytes = source.encode("utf-8")
    tree = _validated_tree_sitter_tree(source, source_bytes)
    return TreeSitterModelBuilder(source, source_bytes).build(tree.root_node)
