# Adapted from the companion proof-carrying-code reader.

"""Reader for ordinary (uncompressed), single-file Metamath proofs.

Parsing, scope validation, and assertion-frame construction live here rather
than in the proof kernel. They are still part of the trusted implementation.
Textual names are resolved here; the kernel receives typed statements.
"""

import re
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path

from .kernel import (
    Assertion,
    Constant,
    Expression,
    Hypothesis,
    Statement,
    Symbol,
    TypeHypothesis,
    Variable,
    VariablePair,
    variables_in,
    verify,
)


@dataclass(frozen=True)
class HypothesisBinding:
    label: str
    statement: TypeHypothesis | Hypothesis


@dataclass
class Scope:
    """State restored when a ${ ... $} block ends."""

    variables: dict[str, Variable]
    types: dict[Variable, Constant]
    hypothesis_count: int
    disjoint: set[VariablePair]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def tokens(source: str) -> Iterator[str]:
    """Strip whitespace-delimited, non-nesting $( ... $) comments."""
    require(
        all(32 <= ord(c) <= 126 or c in "\t\r\n\f" for c in source),
        "Metamath source must use printable ASCII and standard whitespace",
    )
    inside = False
    for token in source.split():
        if inside:
            if token == "$)":
                inside = False
            else:
                require("$(" not in token and "$)" not in token, "Malformed comment")
        elif token == "$(":
            inside = True
        else:
            require(token != "$)", "Unexpected comment terminator")
            yield token
    require(not inside, "Unclosed comment")


def check(source: str) -> list[str]:
    """Check every $p in source, or raise ValueError; return checked labels."""
    stream = iter(tokens(source))
    constants: dict[str, Constant] = {}
    variables: dict[str, Variable] = {}
    ever_variables: set[str] = set()
    used_labels: set[str] = set()
    labels: dict[str, Statement] = {}
    types: dict[Variable, Constant] = {}
    all_types: dict[Variable, Constant] = {}
    hypotheses: list[HypothesisBinding] = []
    disjoint: set[VariablePair] = set()
    scopes: list[Scope] = []
    proved: list[str] = []

    def take() -> str:
        token = next(stream, None)
        if token is None:
            raise ValueError("Unexpected end of file")
        return token

    def until(end: str) -> tuple[str, ...]:
        result: list[str] = []
        while (token := take()) != end:
            require("$" not in token, f"Expected {end}, got {token}")
            result.append(token)
        return tuple(result)

    def resolve_symbol(name: str) -> Symbol:
        if name in constants:
            return constants[name]
        require(name in variables, "Undeclared or inactive symbol")
        return variables[name]

    for token in stream:
        if token == "${":
            scopes.append(
                Scope(variables.copy(), types.copy(), len(hypotheses), disjoint.copy())
            )
            continue
        if token == "$}":
            require(bool(scopes), "Unmatched $}")
            scope = scopes.pop()
            variables, types, disjoint = scope.variables, scope.types, scope.disjoint
            for binding in hypotheses[scope.hypothesis_count :]:
                del labels[binding.label]
            del hypotheses[scope.hypothesis_count :]
            continue
        if token in ("$c", "$v", "$d"):
            names = until("$.")
            unique = set(names)
            require(
                bool(names) and len(unique) == len(names),
                "Empty or repeated declaration",
            )
            if token == "$d":
                require(
                    len(names) >= 2 and unique <= variables.keys(),
                    "Invalid $d variables",
                )
                disjoint.update(
                    frozenset(pair)
                    for pair in combinations((variables[name] for name in names), 2)
                )
            else:
                require(
                    not unique & (constants.keys() | variables.keys() | used_labels),
                    "Symbol already in use",
                )
                if token == "$c":
                    require(
                        not scopes and not unique & ever_variables,
                        "Invalid constant declaration",
                    )
                    constants.update((name, Constant(name)) for name in names)
                else:
                    variables.update((name, Variable(name)) for name in names)
                    ever_variables.update(names)
            continue
        require(
            re.fullmatch(r"[A-Za-z0-9_.-]+", token) is not None,
            f"Expected label; includes and other extensions are unsupported: {token}",
        )
        label, kind = token, take()
        require(
            label not in used_labels | constants.keys() | ever_variables,
            "Duplicate label or symbol collision",
        )
        require(kind in ("$f", "$e", "$a", "$p"), f"Unknown statement kind: {kind}")
        names = until("$=" if kind == "$p" else "$.")
        require(bool(names) and names[0] in constants, "Missing or invalid typecode")
        expression = Expression(
            constants[names[0]], tuple(resolve_symbol(name) for name in names[1:])
        )
        used_labels.add(label)
        if kind == "$f":
            if len(expression.body) != 1 or not isinstance(
                expression.body[0], Variable
            ):
                raise ValueError("Invalid $f")
            variable = expression.body[0]
            require(variable not in types, "Variable already has an active $f")
            require(
                all_types.get(variable, expression.typecode) == expression.typecode,
                "Variable changed type",
            )
            types[variable] = all_types[variable] = expression.typecode
            floating = TypeHypothesis(expression.typecode, variable)
            labels[label] = floating
            hypotheses.append(HypothesisBinding(label, floating))
            continue
        mandatory = variables_in(expression.body)
        require(mandatory <= types.keys(), "Variable lacks an active $f")
        if kind == "$e":
            essential = Hypothesis(expression)
            labels[label] = essential
            hypotheses.append(HypothesisBinding(label, essential))
            continue
        for binding in hypotheses:
            if isinstance(binding.statement, Hypothesis):
                mandatory.update(variables_in(binding.statement.expression.body))
        ordered = tuple(
            binding.statement
            for binding in hypotheses
            if isinstance(binding.statement, Hypothesis)
            or binding.statement.variable in mandatory
        )
        distinct = frozenset(pair for pair in disjoint if pair <= mandatory)
        if kind == "$p":
            proof_labels = until("$.")
            require(
                bool(proof_labels)
                and proof_labels[0] != "("
                and "?" not in proof_labels,
                "Expected a complete, uncompressed proof",
            )
            require(
                all(name in labels for name in proof_labels),
                f"Unknown, inactive, or forward proof reference: {label}",
            )
            proof = tuple(labels[name] for name in proof_labels)
            require(
                verify(proof, expression, frozenset(disjoint)),
                f"Invalid proof: {label}",
            )
            proved.append(label)
        labels[label] = Assertion(ordered, distinct, expression)
    require(not scopes, "Unclosed ${ block")
    return proved


def verify_database(source: str) -> dict:
    """Return a JSON-ready result; acceptance is relative to source's axioms.

    This low-level API intentionally supports arbitrary Metamath theories.
    For untrusted generated certificates use verify_certificate instead, with
    an application-owned theory and expected theorem statement.
    """
    try:
        checked = check(source)
    except (ValueError, TypeError) as error:
        return {
            "valid": False,
            "theorem_count": 0,
            "theorem_labels": [],
            "error": str(error),
        }
    return {
        "valid": True,
        "theorem_count": len(checked),
        "theorem_labels": checked,
        "error": None,
    }


def verify_certificate(
    theory: str, certificate: str, expected_label: str, expected_expression: str
) -> dict:
    """Check theorem-only output against a trusted theory and an exact goal.

    The certificate may contain intermediate $p theorems, but cannot add
    axioms, hypotheses, declarations, scopes, includes, or distinct-variable
    assumptions. The final statement must have the expected label and token
    sequence. The trusted theory supplies all available assumptions; its
    clinical suitability is outside this syntactic proof checker.
    """
    try:
        stream = iter(tokens(certificate))
        statements: list[tuple[str, tuple[str, ...]]] = []

        def take() -> str:
            token = next(stream, None)
            require(token is not None, "Truncated proof certificate")
            return token

        def until(end: str) -> tuple[str, ...]:
            result: list[str] = []
            while (token := take()) != end:
                require("$" not in token, "Certificate may contain only $p theorems")
                result.append(token)
            return tuple(result)

        for label in stream:
            require(
                re.fullmatch(r"[A-Za-z0-9_.-]+", label) is not None,
                "Certificate may contain only labeled $p theorems",
            )
            require(take() == "$p", "Certificate may contain only $p theorems")
            expression = until("$=")
            until("$.")
            statements.append((label, expression))
        require(bool(statements), "Empty proof certificate")
        require(statements[-1][0] == expected_label, "Unexpected final theorem label")
        require(
            statements[-1][1] == tuple(tokens(expected_expression)),
            "Certificate theorem does not match the required specification",
        )
        # Check the theory independently, too: an unfinished source comment or
        # scope must not reinterpret certificate bytes at the boundary.
        check(theory)
        result = verify_database(theory + "\n" + certificate)
        if result["valid"]:
            result["certificate_theorem_count"] = len(statements)
        return result
    except (ValueError, TypeError) as error:
        return {
            "valid": False,
            "theorem_count": 0,
            "theorem_labels": [],
            "error": str(error),
        }


if __name__ == "__main__":
    try:
        source = (
            Path(sys.argv[1]).read_text(encoding="ascii")
            if len(sys.argv) > 1
            else sys.stdin.read()
        )
        checked = check(source)
    except (ValueError, OSError) as error:
        sys.exit(f"REJECTED: {error}")
    print(f"Verified {len(checked)} theorem(s): {', '.join(checked)}")
