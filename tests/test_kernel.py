# Adapted from proof-carrying-code/test_checker.py and test_metamath.py.
"""Checks specific to the typed proof representation."""

import unittest

from careloop.kernel import (
    Assertion, Constant, Expression, Hypothesis, TypeHypothesis, Variable,
    substitute, verify,
)


class TypedCheckerTests(unittest.TestCase):
    def test_substitution_uses_symbol_identity_and_is_simultaneous(self) -> None:
        typecode = Constant("t")
        x, y = Variable("x"), Variable("y")
        expression = Expression(typecode, (Constant("x"), x, y))
        self.assertEqual(
            substitute(expression, {x: (y,), y: (x,)}),
            Expression(typecode, (Constant("x"), y, x)),
        )

    def test_resolved_modus_ponens_with_a_compound_substitution(self) -> None:
        wff, turnstile, arrow = Constant("wff"), Constant("|-"), Constant("->")
        ph, ps = Variable("ph"), Variable("ps")
        left, right = Constant("A"), Constant("B")
        premise = (left, arrow, right)
        modus_ponens = Assertion(
            hypotheses=(
                TypeHypothesis(wff, ph),
                TypeHypothesis(wff, ps),
                Hypothesis(Expression(turnstile, (ph,))),
                Hypothesis(Expression(turnstile, (ph, arrow, ps))),
            ),
            distinct=frozenset(),
            conclusion=Expression(turnstile, (ps,)),
        )
        assumptions = (
            Hypothesis(Expression(wff, premise)),
            Hypothesis(Expression(wff, (right,))),
            Hypothesis(Expression(turnstile, premise)),
            Hypothesis(Expression(turnstile, premise + (arrow, right))),
        )
        goal = Expression(turnstile, (right,))
        self.assertTrue(verify((*assumptions, modus_ponens), goal, frozenset()))
        self.assertFalse(verify((*assumptions[:-1], modus_ponens), goal, frozenset()))



"""Small semantic and adversarial fixtures for the uncompressed checker."""

import unittest

from careloop.metamath import check, verify_database, verify_certificate


PAIR = """
$c t P $.
$v x y $.
fx $f t x $.
fy $f t y $.
pair $a t P x y $.
"""

DISTINCT = """
$c t P $.
$v x y u v $.
fx $f t x $.
fy $f t y $.
fu $f t u $.
fv $f t v $.
${ $d x y $. pair $a t P x y $. $}
"""

INTERLEAVED = """
$c t |- $.
$v x y $.
fx $f t x $.
${
  hx $e |- x $.
  fy $f t y $.
  rule $a |- y $.
$}
fy2 $f t y $.
${
  hx2 $e |- x $.
  th $p |- y $= fx hx2 fy2 rule $.
$}
"""


class MetamathTests(unittest.TestCase):
    def invalid(self, source):
        with self.assertRaises(ValueError):
            check(source)

    def test_zero_hypothesis_axiom_and_theorem_reuse(self):
        source = "$c t $. ax $a t $. first $p t $= ax $. second $p t $= first $."
        self.assertEqual(check(source), ["first", "second"])

    def test_modus_ponens_with_compound_substitution(self):
        source = """
        $c wff |- ( -> ) $.
        $v p q $.
        wp $f wff p $. wq $f wff q $.
        wi $a wff ( p -> q ) $.
        ${
          minor $e |- p $.
          major $e |- ( p -> q ) $.
          mp $a |- q $.
        $}
        ${
          given $e |- ( p -> q ) $.
          implication $e |- ( ( p -> q ) -> p ) $.
          th $p |- p $= wp wq wi wp given implication mp $.
        $}
        """
        self.assertEqual(check(source), ["th"])

    def test_combined_hypothesis_order_and_scoped_assertion(self):
        self.assertEqual(check(INTERLEAVED), ["th"])
        for proof in ("fx fy2 hx2 rule", "fy2 hx2 fx rule"):
            with self.subTest(proof=proof):
                self.invalid(INTERLEAVED.replace("fx hx2 fy2 rule", proof))

    def test_empty_substitution_preserves_existing_stack(self):
        source = PAIR + "empty $a t $. th $p t P x $= fx empty pair $."
        self.assertEqual(check(source), ["th"])

    def test_simultaneous_substitution(self):
        self.assertEqual(check(PAIR + "th $p t P y x $= fy fx pair $."), ["th"])

    def test_substitution_may_contain_its_original_variable(self):
        source = PAIR + "th $p t P P x y y $= fx fy pair fy pair $."
        self.assertEqual(check(source), ["th"])

    def test_stack_underflow_extra_entries_and_wrong_goal(self):
        for theorem in (
            "th $p t P x y $= fx pair $.",
            "th $p t P x y $= fx fx fy pair $.",
            "th $p t P y x $= fx fy pair $.",
            "th $p t P x y $= $.",
        ):
            with self.subTest(theorem=theorem):
                self.invalid(PAIR + theorem)

    def test_typecode_and_essential_hypothesis_mismatches(self):
        source = INTERLEAVED.replace("fx hx2 fy2 rule", "hx2 fx fy2 rule")
        self.invalid(source)
        self.invalid(INTERLEAVED.replace("hx2 $e |- x", "hx2 $e |- y"))

    def test_distinct_variables_require_explicit_pair_and_no_overlap(self):
        valid = "${ $d u v $. th $p t P u v $= fu fv pair $. $}"
        self.assertEqual(check(DISTINCT + valid), ["th"])
        for theorem in (
            "th $p t P u v $= fu fv pair $.",
            "${ $d u v $. th $p t P u u $= fu fu pair $. $}",
            "${ $d u v $. $} th $p t P u v $= fu fv pair $.",
        ):
            with self.subTest(theorem=theorem):
                self.invalid(DISTINCT + theorem)

    def test_distinct_variables_check_every_substitution_cross_pair(self):
        source = """
        $c t P $. $v x y u v z $.
        fx $f t x $. fy $f t y $.
        fu $f t u $. fv $f t v $. fz $f t z $.
        plain $a t P x y $.
        ${ $d x y $. apart $a t P x y $. $}
        ${
          $d u z $. $d v z $.
          th $p t P P u v z $= fu fv plain fz apart $.
        $}
        """
        self.assertEqual(check(source), ["th"])
        for missing in ("$d u z $.", "$d v z $."):
            with self.subTest(missing=missing):
                self.invalid(source.replace(missing, ""))

    def test_distinct_variables_ignore_constants_and_empty_substitution(self):
        source = DISTINCT + """
        empty $a t $. constant $a t P $.
        th $p t P P $= empty constant pair $.
        """
        self.assertEqual(check(source), ["th"])

    def test_only_mandatory_distinct_pairs_travel_with_assertion(self):
        source = """
        $c t $. $v x y $. fx $f t x $. fy $f t y $.
        ${ $d x y $. identity $a t x $. $}
        th $p t x $= fx identity $.
        """
        self.assertEqual(check(source), ["th"])

    def test_optional_hypotheses_and_distinct_pairs_are_available_in_proof(self):
        source = DISTINCT.replace("$c t P $.", "$c t P C $.") + """
        ${ premise $e t x $. erase $a t C $. $}
        ${
          $d u v $.
          th $p t C $= fu fv pair fu fv pair erase $.
        $}
        """
        self.assertEqual(check(source), ["th"])
        self.invalid(source.replace("$d u v $.", ""))

    def test_hypotheses_expire_at_scope_exit(self):
        for expired in ("hx", "fy"):
            with self.subTest(expired=expired):
                self.invalid(INTERLEAVED.replace("fx hx2 fy2 rule", expired))

    def test_references_cannot_be_self_forward_or_unknown(self):
        for proof in ("th", "later", "missing", "?"):
            with self.subTest(proof=proof):
                self.invalid(f"$c t $. th $p t $= {proof} $. later $a t $.")

    def test_comments_and_nested_scope(self):
        source = """
        $( Proof tokens $a $p ? inside this comment are inert. $)
        $c t $. ${ ${ ax $a t $. $} $}
        th $p t $= $( Another comment. $) ax $.
        """
        self.assertEqual(check(source), ["th"])

    def test_invalid_declarations_and_scope(self):
        for source in (
            "$c t t $.",
            "$c t $. $v t $.",
            "$c t $. $v x $. fx $f t x $. gx $f t x $.",
            "$c t s $. $v x $. ${ fx $f t x $. $} gx $f s x $.",
            "$c t $. $v x $. ${ fx $f t x $. $} fx $f t x $.",
            "$c t $. $v x $. ax $a t x $.",
            "$c t $. ax $a t $. ax $a t $.",
            "$c t $. t $a t $.",
            "$c t $. ${ $v x $. $} $c x $.",
            "$c t $. ${ $v ax $. $} ax $a t $.",
            "$c t $. $v x $. $d x x $.",
            "$c t $. $v x $. $d x missing $.",
            "${ $c t $. $}",
            "$c t $. ${ ax $a t $.",
            "$c t $. $}",
        ):
            with self.subTest(source=source):
                self.invalid(source)

    def test_truncated_input_is_rejected(self):
        for source in ("$c t", "$c t $. ax", "$c t $. ax $a t", "$( unfinished"):
            with self.subTest(source=source):
                self.invalid(source)

    def test_unsupported_encodings_are_rejected(self):
        for source in (
            "$[ missing.mm $]",
            "$c t $. ax $a t $. th $p t $= ( ax ) A $.",
        ):
            with self.subTest(source=source):
                self.invalid(source)


class CertificateBoundaryTests(unittest.TestCase):
    theory = "$c |- good bad $. ax $a |- good $."
    certificate = "patient-safe $p |- good $= ax $."

    def verify_certificate(self, certificate=None, **kwargs):
        return verify_certificate(
            kwargs.get("theory", self.theory),
            self.certificate if certificate is None else certificate,
            kwargs.get("expected_label", "patient-safe"),
            kwargs.get("expected_expression", "|- good"),
        )

    def test_result_contains_checked_theorem_labels(self):
        result = self.verify_certificate()
        self.assertEqual(result, {
            "valid": True, "theorem_count": 1,
            "theorem_labels": ["patient-safe"], "error": None,
            "certificate_theorem_count": 1,
        })

    def test_certificate_allows_checked_intermediate_theorem_only(self):
        result = self.verify_certificate(
            "step $p |- good $= ax $. patient-safe $p |- good $= step $."
        )
        self.assertTrue(result["valid"])
        self.assertEqual(result["certificate_theorem_count"], 2)

    def test_untrusted_axiom_and_premise_injection_is_rejected(self):
        for declaration in (
            "forged $a |- bad $.",
            "forged $e |- bad $.",
            "$v bogus $.",
            "${",
            "$c bogus $.",
        ):
            with self.subTest(declaration=declaration):
                result = self.verify_certificate(declaration + self.certificate)
                self.assertFalse(result["valid"])
                self.assertIn("only", result["error"])

    def test_wrong_expected_label_or_goal_is_rejected(self):
        self.assertFalse(self.verify_certificate(expected_label="different")["valid"])
        self.assertFalse(self.verify_certificate(expected_expression="|- bad")["valid"])

    def test_modified_proof_and_modified_conclusion_are_rejected(self):
        for certificate in (
            "patient-safe $p |- good $= missing-rule $.",
            "patient-safe $p |- good $= ax ax $.",
            "patient-safe $p |- bad $= ax $.",
            "patient-safe $p |- good $= patient-safe $.",
        ):
            with self.subTest(certificate=certificate):
                self.assertFalse(self.verify_certificate(certificate)["valid"])

    def test_theory_cannot_leak_unfinished_comment_or_scope(self):
        for theory in (self.theory + " $(", self.theory + " ${"):
            with self.subTest(theory=theory):
                self.assertFalse(self.verify_certificate(theory=theory)["valid"])

    def test_database_acceptance_does_not_approve_untrusted_axioms(self):
        source = "$c |- bad $. forged $a |- bad $. claim $p |- bad $= forged $."
        # Metamath proves statements relative to provided axioms. The app-facing
        # theorem-only gate prevents this legitimate database from being used
        # as an untrusted certificate for the locked clinical theory.
        self.assertTrue(verify_database(source)["valid"])
        self.assertFalse(self.verify_certificate(source)["valid"])

    def test_empty_and_truncated_certificates_are_rejected(self):
        for certificate in ("", "patient-safe", "patient-safe $p |- good $= ax"):
            with self.subTest(certificate=certificate):
                self.assertFalse(self.verify_certificate(certificate)["valid"])

    def test_checks_remain_enabled_with_python_optimization(self):
        import subprocess
        import sys
        from pathlib import Path

        script = """
from careloop.metamath import verify_certificate
theory = '$c |- good bad $. ax $a |- good $.'
good = verify_certificate(theory, 'goal $p |- good $= ax $.', 'goal', '|- good')
bad = verify_certificate(theory, 'goal $p |- bad $= ax $.', 'goal', '|- bad')
forged = verify_certificate(theory, 'f $a |- bad $. goal $p |- bad $= f $.', 'goal', '|- bad')
if not good['valid'] or bad['valid'] or forged['valid']:
    raise SystemExit(1)
"""
        completed = subprocess.run(
            [sys.executable, "-O", "-c", script],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)


class ProofIntegrationBoundaryTests(unittest.TestCase):
    def test_parser_rejects_expansion_before_constructing_oversized_terms(self):
        """A small AST can otherwise duplicate its continuation exponentially."""
        import ast
        from unittest.mock import patch
        from careloop import engine

        source = (
            "def care(s):\n"
            + "    if s.final:\n        if s.family:\n            return \"resolved\"\n" * 15
            + "    return \"await_culture\"\n"
        )
        self.assertLess(len(list(ast.walk(ast.parse(source)))), 300)
        real_branch = engine.mm.branch

        def bounded_branch(condition, yes, no):
            # Check the allocation boundary, not just eventual parser rejection.
            self.assertLessEqual(len(condition.text) + len(yes.text) + len(no.text), 24000)
            return real_branch(condition, yes, no)

        engine.parse_source.cache_clear()
        with patch.object(engine.mm, "branch", side_effect=bounded_branch):
            with self.assertRaisesRegex(ValueError, "Expanded decision tree"):
                engine.parse_source(source)


if __name__ == "__main__":
    unittest.main()
