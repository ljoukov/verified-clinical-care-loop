"""Fixed, finite semantics for the demo language, expressed as Metamath rules.

The trusted theory contains syntax, Boolean/decision evaluation and a finite
universal-introduction rule. It contains NO patient-specific success axioms.
The domain is exactly eight independent booleans (256 assignments).
"""
from dataclasses import dataclass
from itertools import product

FIELDS = ('final', 'authorised', 'current', 'susceptible', 'exception', 'family', 'access', 'overdue')
ACTIONS = ('await_culture', 'request_review', 'escalate_review', 'contact_family', 'confirm_access', 'resolved')
VARIABLES = {'ve': 'env', 'va': 'action', 'vb': 'action', 'vx': 'expr', 'vy': 'expr', 'vp': 'program', 'vq': 'program', **{f'vu{i}': 'bit' for i in range(8)}}

@dataclass(frozen=True)
class Term:
    kind: str
    text: str
    proof: tuple[str, ...]

class Theory:
    def __init__(self):
        constants = ['bit', 'action', 'env', 'expr', 'program', '|-', 'T', 'F', '(', ')', 'not', 'and', 'or', 'is', 'ret', 'if', 'E', 'B', 'P', 'C', 'safe', 'none', *FIELDS, *ACTIONS]
        self.lines = [
            '$( Fixed semantics: 8 Boolean inputs, 6 actions, total acyclic decisions. $)',
            '$c ' + ' '.join(dict.fromkeys(constants)) + ' $.',
            '$v ' + ' '.join(VARIABLES) + ' $.',
            *[f'f-{v} $f {t} {v} $.' for v,t in VARIABLES.items()],
        ]
        self.rules = {}
        self._build()

    def rule(self, name, conclusion, premises=()):
        tokens = set((' '.join(premises) + ' ' + conclusion).split())
        self.rules[name] = tuple(v for v in VARIABLES if v in tokens)
        if premises:
            self.lines.append('${')
            self.lines.extend(f'{name}-h{i} $e {p} $.' for i,p in enumerate(premises))
        self.lines.append(f'{name} $a {conclusion} $.')
        if premises: self.lines.append('$}')

    def apply(self, name, values=None, premises=()):
        values = values or {}
        return tuple(label for v in self.rules[name] for label in values[v].proof) + tuple(label for p in premises for label in p) + (name,)

    def _build(self):
        for bit in ('T','F'):
            self.rule('bit-'+bit, 'bit '+bit)
            self.rule('expr-'+bit, 'expr '+bit)
            self.rule('eval-'+bit, f'|- B ve va {bit} {bit}')
        for a in (*ACTIONS, 'none'): self.rule('action-'+a, 'action '+a)
        for f in FIELDS: self.rule('expr-'+f, 'expr '+f)
        self.rule('expr-not', 'expr ( not vx )')
        for op in ('and','or'): self.rule('expr-'+op, f'expr ( {op} vx vy )')
        self.rule('expr-is', 'expr ( is va )')
        self.rule('program-ret', 'program ( ret va )')
        self.rule('program-if', 'program ( if vx vp vq )')
        env = '( E ' + ' '.join(f'vu{i}' for i in range(8)) + ' )'
        self.rule('env-make', 'env '+env)
        for i,f in enumerate(FIELDS): self.rule('lookup-'+f, f'|- B {env} va {f} vu{i}')
        for a,b in [('T','F'),('F','T')]:
            self.rule('not-'+a, f'|- B ve va ( not vx ) {b}', [f'|- B ve va vx {a}'])
        self.rule('and-F', '|- B ve va ( and vx vy ) F', ['|- B ve va vx F'])
        self.rule('or-T', '|- B ve va ( or vx vy ) T', ['|- B ve va vx T'])
        for b in ('T','F'):
            self.rule('and-T'+b, f'|- B ve va ( and vx vy ) {b}', ['|- B ve va vx T', f'|- B ve va vy {b}'])
            self.rule('or-F'+b, f'|- B ve va ( or vx vy ) {b}', ['|- B ve va vx F', f'|- B ve va vy {b}'])
        self.rule('is-same', '|- B ve va ( is va ) T')
        for a in (*ACTIONS,'none'):
            for b in (*ACTIONS,'none'):
                if a != b: self.rule(f'is-{a}-{b}', f'|- B ve {a} ( is {b} ) F')
        self.rule('eval-ret', '|- P ve ( ret va ) va')
        self.rule('eval-if-T', '|- P ve ( if vx vp vq ) va', ['|- B ve none vx T', '|- P ve vp va'])
        self.rule('eval-if-F', '|- P ve ( if vx vp vq ) va', ['|- B ve none vx F', '|- P ve vq va'])
        self.rule('compliance', '|- C ve vp vx', ['|- P ve vp va', '|- B ve va vx T'])
        cases = [f'|- C ( E {" ".join("T" if b else "F" for b in bits)} ) vp vx' for bits in product((False, True), repeat=8)]
        self.lines.append('$( Finite universal introduction: all 256 assignments, no omitted states. $)')
        self.rule('complete-domain', '|- safe vp vx', cases)

    @property
    def source(self): return '\n'.join(self.lines) + '\n'

THEORY = Theory()


def atom(value, kind='expr'):
    text = ('T' if value else 'F') if type(value) is bool else value
    return Term(kind, text, (kind+'-'+text,))


def expr(op, *args):
    values = {'vx': args[0]}
    if len(args)>1: values['vy'] = args[1]
    return Term('expr', f'( {op} {" ".join(a.text for a in args)} )', THEORY.apply('expr-'+op,values))


def is_action(action):
    a=atom(action,'action')
    return Term('expr',f'( is {action} )',THEORY.apply('expr-is',{'va':a}))


def ret(action):
    a=atom(action,'action')
    return Term('program',f'( ret {action} )',THEORY.apply('program-ret',{'va':a}))


def branch(condition, yes, no):
    return Term('program',f'( if {condition.text} {yes.text} {no.text} )',THEORY.apply('program-if',{'vx':condition,'vp':yes,'vq':no}))


def environment(state):
    bits=[atom(state[f],'bit') for f in FIELDS]
    return Term('env','( E '+' '.join(b.text for b in bits)+' )',THEORY.apply('env-make',{f'vu{i}':b for i,b in enumerate(bits)}))
