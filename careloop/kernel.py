# Adapted from the companion proof-carrying-code checker.

"""Typed Metamath proof kernel; source notation belongs to metamath.py.

The reader validates declarations, builds assertion frames, and resolves proof
labels to active hypotheses, axioms, or already checked theorems. This kernel
trusts those inputs: constructing an Assertion here does not prove it.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TypeAlias


@dataclass(frozen=True)
class Constant:
    name: str


@dataclass(frozen=True)
class Variable:
    name: str


Symbol: TypeAlias = Constant | Variable
Body: TypeAlias = tuple[Symbol, ...]
VariablePair: TypeAlias = frozenset[Variable]
DistinctPairs: TypeAlias = frozenset[VariablePair]
Substitution: TypeAlias = Mapping[Variable, Body]


@dataclass(frozen=True)
class Expression:
    typecode: Constant
    body: Body


@dataclass(frozen=True)
class TypeHypothesis:
    """A variable's type declaration ($f)."""

    typecode: Constant
    variable: Variable

    @property
    def expression(self) -> Expression:
        return Expression(self.typecode, (self.variable,))


@dataclass(frozen=True)
class Hypothesis:
    """An assumed expression ($e)."""

    expression: Expression


@dataclass(frozen=True)
class Assertion:
    """An axiom or checked theorem, together with its mandatory hypotheses."""

    hypotheses: tuple[TypeHypothesis | Hypothesis, ...]
    distinct: DistinctPairs
    conclusion: Expression


Statement: TypeAlias = TypeHypothesis | Hypothesis | Assertion


def substitute(expression: Expression, substitution: Substitution) -> Expression:
    """Replace variables simultaneously, without rewriting the replacements."""
    body: list[Symbol] = []
    for symbol in expression.body:
        body.extend(substitution[symbol] if isinstance(symbol, Variable) else (symbol,))
    return Expression(expression.typecode, tuple(body))


def variables_in(body: Body) -> set[Variable]:
    return {symbol for symbol in body if isinstance(symbol, Variable)}


def verify(
    proof: Sequence[Statement], goal: Expression, disjoint: DistinctPairs
) -> bool:
    """Check a resolved proof against its goal and the active $d restrictions."""
    stack: list[Expression] = []
    for step in proof:
        # An active type declaration or assumption is available without a proof.
        # Push its expression so a later assertion can use it as a premise.
        if isinstance(step, (TypeHypothesis, Hypothesis)):
            stack.append(step.expression)
            continue

        # Otherwise, apply an axiom or previously checked theorem. Its N
        # mandatory hypotheses must match the last N expressions on the stack.
        start = len(stack) - len(step.hypotheses)
        if start < 0:
            # Fewer than N premises are available: this proof step is invalid.
            return False
        arguments = stack[start:]
        substitution: dict[Variable, Body] = {}

        # Type hypotheses determine the substitutions for this assertion.
        for hypothesis, actual in zip(step.hypotheses, arguments):
            if isinstance(hypothesis, TypeHypothesis):
                if hypothesis.typecode != actual.typecode:
                    return False
                substitution[hypothesis.variable] = actual.body

        # All hypotheses must match under the same simultaneous substitution.
        for hypothesis, actual in zip(step.hypotheses, arguments):
            if substitute(hypothesis.expression, substitution) != actual:
                return False

        for left, right in step.distinct:
            for a in variables_in(substitution[left]):
                for b in variables_in(substitution[right]):
                    if a == b or frozenset((a, b)) not in disjoint:
                        return False

        stack[start:] = [substitute(step.conclusion, substitution)]
    return stack == [goal]
