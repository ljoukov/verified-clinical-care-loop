"""Restricted Python workflows, independent requirements, and actual certificates.

This demo proves total decision behavior for all 256 inputs in an eight-Boolean
abstraction. Clinical record interpretation, scheduling, and delivery are outside
that theorem. Source is parsed and interpreted; generated Python is never exec'd.
"""
import ast
from dataclasses import dataclass
from functools import lru_cache
from hashlib import sha256
from itertools import product
from time import perf_counter
from . import theory as mm
from .metamath import verify_certificate

FIELDS = mm.FIELDS
ACTIONS = mm.ACTIONS
DEFAULT_SOURCE = '''def care(s):
    if not s.final:
        return "await_culture"

    if not s.authorised or not s.current:
        if s.overdue:
            return "escalate_review"
        return "request_review"

    if not s.susceptible and not s.exception:
        if s.overdue:
            return "escalate_review"
        return "request_review"

    if not s.family:
        return "contact_family"
    if not s.access:
        return "confirm_access"
    return "resolved"
'''
SPEC_SOURCE = '''# Independently approved demo specification; the generator cannot edit it.
valid_plan = s.authorised and s.current and (s.susceptible or s.exception)
allowed = (
    (action == "await_culture" and not s.final)
    or (action == "request_review" and s.final and not valid_plan and not s.overdue)
    or (action == "escalate_review" and s.final and not valid_plan and s.overdue)
    or (action == "contact_family" and s.final and valid_plan and not s.family)
    or (action == "confirm_access" and s.final and valid_plan and s.family and not s.access)
    or (action == "resolved" and s.final and valid_plan and s.family and s.access)
)
# Required: allowed is True for EVERY assignment of the eight Boolean inputs.
'''
REQUIREMENTS = [
    {'id':'R1','title':'Keep pending cultures open','description':'Await the culture while it is pending; a final result must advance to an appropriate action.','expression':'not final → await_culture'},
    {'id':'R2','title':'Use an authorised, current plan','description':'Missing clinician authority or outdated evidence requires clinical review.','expression':'final and (not authorised or not current) → review'},
    {'id':'R3','title':'Resolve treatment conflicts','description':'A non-susceptible or unknown result requires review unless the current plan has an authorised exception.','expression':'final and not (susceptible or exception) → review'},
    {'id':'R4','title':'Escalate overdue review','description':'When clinical review is needed, the decision changes from request_review to escalate_review at the configured deadline.','expression':'review_needed → (escalate_review if overdue else request_review)'},
    {'id':'R5','title':'Confirm family instructions','description':'After an acceptable current plan, contact the family until instructions are confirmed for that plan.','expression':'final and valid_plan and not family → contact_family'},
    {'id':'R6','title':'Confirm treatment access','description':'After family acknowledgement, confirm treatment access; resolve only when every prerequisite holds.','expression':'final and valid_plan and family → (resolved if access else confirm_access)'},
]
FIELD_DESCRIPTIONS = {
    'final':'Culture C17 has a final result.',
    'authorised':'The plan is approved by an authorised clinician.',
    'current':'Plan evidence matches the current patient, culture, result, and medication versions.',
    'susceptible':'The latest result reports susceptibility to the planned treatment; unknown maps to false.',
    'exception':'A clinician has authorised an exception for this current plan and evidence.',
    'family':'Family instructions are confirmed for this plan.',
    'access':'Treatment access is confirmed for this plan.',
    'overdue':'The configured clinical review deadline has been reached.',
}

@dataclass(frozen=True)
class Node:
    op: str
    args: tuple
    value: object
    term: mm.Term


def literal(value): return Node('literal',(),value,mm.atom(value))
def field(name): return Node('field',(),name,mm.atom(name))
def operation(op,*args): return Node(op,tuple(args),None,mm.expr(op,*(a.term for a in args)))
def is_action(action): return Node('is',(),action,mm.is_action(action))
def conjunction(*args):
    n=args[0]
    for a in args[1:]: n=operation('and',n,a)
    return n

def disjunction(*args):
    n=args[0]
    for a in args[1:]: n=operation('or',n,a)
    return n

def program_return(action): return Node('ret',(),action,mm.ret(action))
def program_if(condition,yes,no):
    # Reject before copying shared fallbacks into the canonical tree. Otherwise
    # a short source can cause exponential allocation during normalization.
    if len(condition.term.text)+len(yes.term.text)+len(no.term.text)+10>24000:
        raise ValueError('Expanded decision tree exceeds the demo limit.')
    return Node('if',(condition,yes,no),None,mm.branch(condition.term,yes.term,no.term))


def _specification():
    f={name:field(name) for name in FIELDS}
    valid=conjunction(f['authorised'],f['current'],disjunction(f['susceptible'],f['exception']))
    invalid=operation('not',valid)
    requirements=(
        conjunction(is_action('await_culture'),operation('not',f['final'])),
        conjunction(is_action('request_review'),f['final'],invalid,operation('not',f['overdue'])),
        conjunction(is_action('escalate_review'),f['final'],invalid,f['overdue']),
        conjunction(is_action('contact_family'),f['final'],valid,operation('not',f['family'])),
        conjunction(is_action('confirm_access'),f['final'],valid,f['family'],operation('not',f['access'])),
        conjunction(is_action('resolved'),f['final'],valid,f['family'],f['access']),
    )
    return disjunction(*requirements)

SPEC = _specification()
SPEC_HASH = sha256(SPEC.term.text.encode()).hexdigest()
THEORY_HASH = sha256(mm.THEORY.source.encode()).hexdigest()


def _parse_expression(n):
    if isinstance(n,ast.Attribute) and isinstance(n.value,ast.Name) and n.value.id=='s' and n.attr in FIELDS:
        return field(n.attr)
    if isinstance(n,ast.Constant) and type(n.value) is bool: return literal(n.value)
    if isinstance(n,ast.UnaryOp) and isinstance(n.op,ast.Not): return operation('not',_parse_expression(n.operand))
    if isinstance(n,ast.BoolOp) and isinstance(n.op,(ast.And,ast.Or)):
        args=[_parse_expression(v) for v in n.values]
        return (conjunction if isinstance(n.op,ast.And) else disjunction)(*args)
    raise ValueError('Only the eight s.<field> Boolean inputs, True/False, not, and, and or are allowed in conditions.')


def _parse_block(statements,fallback=None):
    tail=fallback
    for i in range(len(statements)-1,-1,-1):
        n=statements[i]
        if isinstance(n,ast.Return):
            if i!=len(statements)-1: raise ValueError('Unreachable statements after return are not supported.')
            if not isinstance(n.value,ast.Constant) or type(n.value.value) is not str or n.value.value not in ACTIONS:
                raise ValueError('Return one of the six approved action strings.')
            tail=program_return(n.value.value)
        elif isinstance(n,ast.If):
            condition=_parse_expression(n.test)
            yes=_parse_block(n.body,tail)
            no=_parse_block(n.orelse,tail) if n.orelse else tail
            if yes is None or no is None: raise ValueError('Every possible path must return an action.')
            tail=program_if(condition,yes,no)
        else: raise ValueError('The workflow language supports only if/elif/else and literal action returns.')
    return tail


@lru_cache(maxsize=64)
def parse_source(source):
    if type(source) is not str or len(source)>12000: raise ValueError('Source must be text of at most 12,000 characters.')
    try: tree=ast.parse(source)
    except SyntaxError as exc: raise ValueError(f'Invalid syntax at line {exc.lineno}: {exc.msg}') from exc
    if len(list(ast.walk(tree)))>300: raise ValueError('Workflow exceeds the 300-node demo limit.')
    if len(tree.body)!=1 or not isinstance(tree.body[0],ast.FunctionDef): raise ValueError('Provide exactly one function: def care(s):')
    fn=tree.body[0]
    if (fn.name!='care' or fn.decorator_list or fn.returns or fn.type_comment or fn.args.posonlyargs or fn.args.kwonlyargs or fn.args.vararg or fn.args.kwarg or fn.args.defaults or fn.args.kw_defaults or len(fn.args.args)!=1 or fn.args.args[0].arg!='s' or fn.args.args[0].annotation or getattr(fn,'type_params',[])):
        raise ValueError('The function must have the exact signature def care(s): without decorators or annotations.')
    result=_parse_block(fn.body)
    if result is None: raise ValueError('The workflow must return an action.')
    if len(result.term.text)>24000: raise ValueError('Expanded decision tree exceeds the demo limit.')
    return result


def _state(state):
    if not isinstance(state,dict): raise ValueError('State must be an object containing exactly the eight Boolean fields.')
    if set(state)!=set(FIELDS): raise ValueError('State must contain exactly: '+', '.join(FIELDS))
    if any(type(state[f]) is not bool for f in FIELDS): raise ValueError('Every state value must be a Boolean (not an integer or string).')
    return {f:state[f] for f in FIELDS}


def _bool(node,state,action='none'):
    if node.op=='literal': return node.value
    if node.op=='field': return state[node.value]
    if node.op=='is': return action==node.value
    if node.op=='not': return not _bool(node.args[0],state,action)
    if node.op=='and': return _bool(node.args[0],state,action) and _bool(node.args[1],state,action)
    if node.op=='or': return _bool(node.args[0],state,action) or _bool(node.args[1],state,action)
    raise ValueError('Unknown Boolean expression.')


def _run(node,state,trace=None):
    while node.op=='if':
        condition,yes,no=node.args
        value=_bool(condition,state)
        if trace is not None: trace.append({'expression':condition.term.text,'value':value,'branch':'then' if value else 'else'})
        node=yes if value else no
    return node.value


def evaluate(source,state):
    """Interpret the same immutable syntax used by the proof, without exec().

    The HTTP execution boundary additionally requires a valid certificate first.
    This lower-level function also permits counterexample replay in tests.
    """
    state=_state(state)
    trace=[]
    action=_run(parse_source(source),state,trace)
    return {'action':action,'state':state,'trace':trace,'satisfies_spec':_bool(SPEC,state,action),'sandbox':True}


def _prove_bool(node,state,env,action):
    """Generate an explicit evaluation derivation; correctness is checked later."""
    a=mm.atom(action,'action')
    values={'ve':env,'va':a}
    if node.op=='literal':
        bit='T' if node.value else 'F'
        return node.value,mm.THEORY.apply('eval-'+bit,values)
    if node.op=='field':
        values.update({f'vu{i}':mm.atom(state[f],'bit') for i,f in enumerate(FIELDS)})
        return state[node.value],mm.THEORY.apply('lookup-'+node.value,values)
    if node.op=='is':
        same=action==node.value
        rule='is-same' if same else f'is-{action}-{node.value}'
        return same,mm.THEORY.apply(rule,values)
    x=node.args[0]
    v,p=_prove_bool(x,state,env,action)
    values['vx']=x.term
    if node.op=='not': return not v,mm.THEORY.apply('not-'+('T' if v else 'F'),values,[p])
    y=node.args[1]
    values['vy']=y.term
    if node.op=='and' and not v: return False,mm.THEORY.apply('and-F',values,[p])
    if node.op=='or' and v: return True,mm.THEORY.apply('or-T',values,[p])
    w,q=_prove_bool(y,state,env,action)
    name=('and-T' if node.op=='and' else 'or-F')+('T' if w else 'F')
    return w,mm.THEORY.apply(name,values,[p,q])


def _prove_program(node,state,env):
    if node.op=='ret':
        a=mm.atom(node.value,'action')
        return node.value,mm.THEORY.apply('eval-ret',{'ve':env,'va':a})
    condition,yes,no=node.args
    value,condition_proof=_prove_bool(condition,state,env,'none')
    action,branch_proof=_prove_program(yes if value else no,state,env)
    return action,mm.THEORY.apply('eval-if-'+('T' if value else 'F'),{'ve':env,'va':mm.atom(action,'action'),'vx':condition.term,'vp':yes.term,'vq':no.term},[condition_proof,branch_proof])


def _violations(s,action):
    valid=s['authorised'] and s['current'] and (s['susceptible'] or s['exception'])
    needs=s['final'] and not valid
    found=[]
    def add(id,message): found.append({'id':id,'message':message})
    if not s['final'] and action!='await_culture': add('R1','The culture is pending; the workflow must await it.')
    if s['final'] and action=='await_culture': add('R1','A final culture cannot be ignored by waiting forever.')
    review='escalate_review' if s['overdue'] else 'request_review'
    if needs and action!=review:
        if not s['authorised'] or not s['current']: add('R2','The plan is missing clinician authority or uses outdated evidence.')
        if not s['susceptible'] and not s['exception']: add('R3','The treatment is not reported susceptible, and no authorised exception exists.')
        add('R4','Clinical review must '+('escalate now.' if s['overdue'] else 'be requested before its deadline.'))
    if s['final'] and valid and not s['family'] and action!='contact_family': add('R5','Family instructions have not been confirmed for this plan.')
    if s['final'] and valid and s['family']:
        expected='resolved' if s['access'] else 'confirm_access'
        if action!=expected: add('R6','Resolve once every prerequisite holds.' if s['access'] else 'Treatment access has not been confirmed for this plan.')
    if not found: add('SPEC','The action does not satisfy the independently approved decision relation.')
    return found


def expected_statement(source):
    return '|- safe '+parse_source(source).term.text+' '+SPEC.term.text


def check_certificate(source,certificate):
    """Check an untrusted certificate against locally fixed semantics/specification."""
    return verify_certificate(mm.THEORY.source,certificate,'care-safe',expected_statement(source))


def verify_source(source):
    start=perf_counter()
    source_hash=sha256(source.encode()).hexdigest() if isinstance(source,str) else ''
    base={'code_hash':source_hash,'source_hash':source_hash,'spec_hash':SPEC_HASH,'theory_hash':THEORY_HASH,'domain_size':256,'fields':list(FIELDS),'sandbox':True,'proof_kind':'Metamath substitution proof over the complete 256-state Boolean domain'}
    try: program=parse_source(source)
    except (ValueError,TypeError,RecursionError) as exc:
        return {**base,'valid':False,'error':str(exc),'states_checked':0,'elapsed_ms':round((perf_counter()-start)*1000,2),'violations':[{'id':'LANGUAGE','message':str(exc)}],'trace':[]}
    base['program_hash']=sha256(program.term.text.encode()).hexdigest()
    failures=[]
    states=[]
    for bits in product((False,True),repeat=8):
        state=dict(zip(FIELDS,bits)); action=_run(program,state)
        states.append(state)
        if not _bool(SPEC,state,action): failures.append({'state':state,'action':action,'violations':_violations(state,action)})
    if failures:
        counterexample=next((f for f in failures if f['action']=='resolved'),failures[0])
        return {**base,'valid':False,'error':'The candidate violates the approved specification.','states_checked':256,'failing_states':len(failures),'counterexample':counterexample,'violations':counterexample['violations'],'elapsed_ms':round((perf_counter()-start)*1000,2),'proof_steps':0,'trace':[{'title':'Counterexample found','detail':f'{len(failures)} of 256 assignments violate the independent requirements.'}]}
    rows=[]
    for state in states:
        env=mm.environment(state)
        action,program_proof=_prove_program(program,state,env)
        truth,spec_proof=_prove_bool(SPEC,state,env,action)
        if not truth: raise RuntimeError('Internal proof generator disagrees with the independently evaluated specification.')
        rows.append(mm.THEORY.apply('compliance',{'ve':env,'va':mm.atom(action,'action'),'vp':program.term,'vx':SPEC.term},[program_proof,spec_proof]))
    proof=mm.THEORY.apply('complete-domain',{'vp':program.term,'vx':SPEC.term},rows)
    statement='|- safe '+program.term.text+' '+SPEC.term.text
    certificate='care-safe $p '+statement+' $=\n'+' '.join(proof)+' $.\n'
    checked=check_certificate(source,certificate)
    if not checked['valid']:
        return {**base,'valid':False,'error':'Independent checker rejected generated proof: '+str(checked.get('error')),'states_checked':256,'elapsed_ms':round((perf_counter()-start)*1000,2),'proof_steps':len(proof),'trace':[]}
    full_certificate=mm.THEORY.source+'\n'+certificate
    return {**base,'valid':True,'states_checked':256,'failing_states':0,'elapsed_ms':round((perf_counter()-start)*1000,2),'proof_steps':len(proof),'theorem_count':checked['theorem_count'],'theorem':'care-safe','statement':statement,'certificate':full_certificate,'proof_certificate':certificate,'certificate_hash':sha256(full_certificate.encode()).hexdigest(),'certificate_bytes':len(full_certificate.encode()),'violations':[],'trace':[
        {'title':'Parse the exact program','detail':'Restricted Python is translated to one immutable decision tree used for both execution and proof.'},
        {'title':'Apply the fixed requirements','detail':'The specification and semantics are owned by the verifier; candidate code cannot replace them.'},
        {'title':'Derive each possible execution','detail':'Boolean and if-return inference rules derive the actual action and specification truth for all 256 assignments.'},
        {'title':'Prove the complete finite domain','detail':'The complete-domain rule consumes all 256 case proofs with the same exact program and specification.'},
        {'title':'Check every substitution independently','detail':f'The Metamath-inspired checker accepted {len(proof):,} explicit proof steps and the exact required theorem.'},
    ]}


def catalog():
    resistance='''    if not s.susceptible and not s.exception:
        if s.overdue:
            return "escalate_review"
        return "request_review"

'''
    variants=[
        {'id':'correct','name':'Complete care workflow','description':'Satisfies all six approved requirements.','source':DEFAULT_SOURCE},
        {'id':'unsafe_resistance','name':'Skip resistance review','description':'Remove the treatment conflict guard; administrative confirmations can incorrectly resolve the case.','source':DEFAULT_SOURCE.replace(resistance,'')},
        {'id':'stale_evidence','name':'Accept an outdated plan','description':'Remove the current-evidence condition and accept approvals tied to an earlier result.','source':DEFAULT_SOURCE.replace('not s.authorised or not s.current','not s.authorised')},
        {'id':'never_act','name':'Wait forever','description':'A vacuous candidate that never resolves anything still fails the progress requirements.','source':'def care(s):\n    return "await_culture"\n'},
    ]
    return {'name':'Verified Clinical Care Loop','default_source':DEFAULT_SOURCE,'variants':variants,'requirements':REQUIREMENTS,'spec_source':SPEC_SOURCE,'spec_hash':SPEC_HASH,'theory_hash':THEORY_HASH,'fields':[{'name':f,'label':f.replace('_',' ').title(),'description':FIELD_DESCRIPTIONS[f]} for f in FIELDS],'actions':list(ACTIONS),'domain_size':256,'initial_state':dict(zip(FIELDS,[True,True,True,False,False,False,False,False])),'patient':{'id':'DAVID-66','name':'David','age':66,'culture':'C17','treatment':'TMP-SMX','symptoms':'Acute-on-chronic confusion; urinary infection','source_title':'AHRQ PSNet: Treatment Challenges After Discharge','source_url':'https://psnet.ahrq.gov/web-mm/treatment-challenges-after-discharge','provenance':'Inspired by the published AHRQ case. David and C17 are demo aliases. This replay is synthetic and is not a Stanford patient export.'},'scope':'All 256 combinations of eight Boolean inputs; the result proves the decision relation, not clinical truth, real-world delivery, or patient outcomes.','generation_mode':'Prebuilt candidate examples; no live LLM connected.'}
