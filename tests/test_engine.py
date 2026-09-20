import unittest
from itertools import product
from careloop.engine import (
    ACTIONS, DEFAULT_SOURCE, FIELDS, SPEC, catalog, check_certificate,
    evaluate, parse_source, verify_source,
)
from careloop.metamath import verify_database


class EngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.verified=verify_source(DEFAULT_SOURCE)

    def test_real_proof_and_standalone_download(self):
        result=self.verified
        self.assertTrue(result['valid'],result.get('error'))
        self.assertEqual(result['states_checked'],256)
        self.assertEqual(result['theorem_count'],1)
        self.assertGreater(result['proof_steps'],1000)
        self.assertTrue(verify_database(result['certificate'])['valid'])

    def test_all_runtime_states_obey_independent_spec(self):
        seen=set()
        for bits in product((False,True),repeat=len(FIELDS)):
            result=evaluate(DEFAULT_SOURCE,dict(zip(FIELDS,bits)))
            self.assertTrue(result['satisfies_spec'])
            seen.add(result['action'])
        self.assertEqual(seen,set(ACTIONS))

    def test_demonstration_failures_have_replayable_counterexamples(self):
        for candidate in catalog()['variants'][1:]:
            with self.subTest(candidate=candidate['id']):
                result=verify_source(candidate['source'])
                self.assertFalse(result['valid'])
                counterexample=result['counterexample']
                replay=evaluate(candidate['source'],counterexample['state'])
                self.assertFalse(replay['satisfies_spec'])
                self.assertEqual(replay['action'],counterexample['action'])
                self.assertGreater(result['failing_states'],0)

    def test_resistance_bug_cannot_hide_behind_administrative_completion(self):
        source=catalog()['variants'][1]['source']
        state=dict.fromkeys(FIELDS,True)
        state.update(susceptible=False,exception=False,overdue=False)
        self.assertEqual(evaluate(source,state)['action'],'resolved')
        self.assertEqual(evaluate(DEFAULT_SOURCE,state)['action'],'request_review')
        self.assertIn('R3',[v['id'] for v in verify_source(source)['violations']])

    def test_correction_reopens_review_and_deadline_escalates(self):
        state=dict.fromkeys(FIELDS,True)
        self.assertEqual(evaluate(DEFAULT_SOURCE,state)['action'],'resolved')
        state.update(current=False,overdue=False)
        self.assertEqual(evaluate(DEFAULT_SOURCE,state)['action'],'request_review')
        state['overdue']=True
        self.assertEqual(evaluate(DEFAULT_SOURCE,state)['action'],'escalate_review')

    def test_certificate_is_bound_to_exact_program(self):
        changed=DEFAULT_SOURCE.replace('if not s.final:','if not s.final or False:')
        self.assertNotEqual(parse_source(changed).term.text,parse_source(DEFAULT_SOURCE).term.text)
        self.assertFalse(check_certificate(changed,self.verified['proof_certificate'])['valid'])

    def test_fixed_spec_cannot_be_replaced_with_true(self):
        weakened=self.verified['proof_certificate'].replace(SPEC.term.text,'T',1)
        self.assertFalse(check_certificate(DEFAULT_SOURCE,weakened)['valid'])

    def test_case_proof_cannot_be_omitted(self):
        missing=self.verified['proof_certificate'].replace(' compliance ',' ',1)
        self.assertFalse(check_certificate(DEFAULT_SOURCE,missing)['valid'])

    def test_extra_axiom_is_rejected(self):
        certificate='injected $a |- safe T T $.\n'+self.verified['proof_certificate']
        self.assertFalse(check_certificate(DEFAULT_SOURCE,certificate)['valid'])

    def test_formatting_preserves_semantics_but_changes_source_hash(self):
        a=parse_source(DEFAULT_SOURCE)
        b=parse_source('# harmless formatting\n'+DEFAULT_SOURCE)
        self.assertEqual(a.term,b.term)
        self.assertTrue(check_certificate('# harmless formatting\n'+DEFAULT_SOURCE,self.verified['proof_certificate'])['valid'])

    def test_invalid_state_values_are_not_coerced(self):
        for bad in (1,0,None,'false',[],{}):
            with self.subTest(bad=bad):
                state=dict.fromkeys(FIELDS,False);state['final']=bad
                with self.assertRaises(ValueError): evaluate(DEFAULT_SOURCE,state)
        with self.assertRaises(ValueError): evaluate(DEFAULT_SOURCE,{})
        with self.assertRaises(ValueError): evaluate(DEFAULT_SOURCE,{**dict.fromkeys(FIELDS,False),'extra':True})

    def test_language_boundary(self):
        bad_sources=[
            'import os\n'+DEFAULT_SOURCE,
            '@wrapper\n'+DEFAULT_SOURCE,
            DEFAULT_SOURCE.replace('def care(s):','def care(s=None):'),
            DEFAULT_SOURCE.replace('s.final','s.unknown'),
            'def care(s):\n    return "none"\n',
            'def care(s):\n    return execute()\n',
            'def care(s):\n    s.final = True\n    return "resolved"\n',
            'def care(s):\n    if s.final:\n        return "resolved"\n',
            'def care(s):\n    while True:\n        return "resolved"\n',
            'def care(s):\n    return "resolved"\n    return "await_culture"\n',
        ]
        for source in bad_sources:
            with self.subTest(source=source):
                result=verify_source(source)
                self.assertFalse(result['valid'])
                self.assertEqual(result['states_checked'],0)


if __name__=='__main__': unittest.main()
