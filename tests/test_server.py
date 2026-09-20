"""Exercise the HTTP execution boundary without opening a listening socket."""
from email.message import Message
from io import BytesIO
import json
import unittest
from unittest.mock import patch

import server
from careloop.engine import DEFAULT_SOURCE, FIELDS, catalog, verify_source


class MemoryHandler(server.Handler):
    def __init__(self, path, body=b'', headers=None):
        self.path=path
        self.rfile=BytesIO(body)
        self.headers=Message()
        defaults={
            'Host':'127.0.0.1:8765',
            'Content-Type':'application/json',
            'Content-Length':str(len(body)),
        }
        defaults.update(headers or {})
        for name,value in defaults.items(): self.headers[name]=value
        self.response=None
        self.logged_errors=[]

    def respond(self,status,content,content_type='application/json; charset=utf-8'):
        self.response=(status,content,content_type)

    def log_error(self,*args):
        self.logged_errors.append(args)


def request(path='/api/evaluate',payload=None,headers=None,raw=None,method='POST'):
    body=raw if raw is not None else json.dumps(payload).encode()
    handler=MemoryHandler(path,body,headers)
    (handler.do_GET if method=='GET' else handler.do_POST)()
    return handler.response


class ServerBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.accepted=verify_source(DEFAULT_SOURCE)
        if not cls.accepted['valid']:
            raise AssertionError(cls.accepted.get('error'))

    def setUp(self):
        server.verification_cache.clear()
        server.verification_cache[DEFAULT_SOURCE]=self.accepted
        self.state=dict.fromkeys(FIELDS,True)
        self.payload={'source':DEFAULT_SOURCE,'state':self.state}

    def tearDown(self):
        server.verification_cache.clear()

    def test_accepted_exact_source_evaluates(self):
        status,body,_=request(payload=self.payload)
        self.assertEqual(status,200)
        self.assertEqual(body['action'],'resolved')
        self.assertEqual(body['code_hash'],self.accepted['code_hash'])
        self.assertTrue(body['simulated'])
        self.assertTrue(body['satisfies_spec'])

    def test_same_origin_is_allowed(self):
        status,body,_=request(payload=self.payload,headers={'Origin':'http://127.0.0.1:8765'})
        self.assertEqual(status,200)
        self.assertEqual(body['action'],'resolved')

    def test_bad_source_cannot_execute(self):
        source=catalog()['variants'][1]['source']
        with patch.object(server.engine,'evaluate') as evaluate:
            status,body,_=request(payload={'source':source,'state':self.state})
        self.assertEqual(status,422)
        self.assertIn('blocked',body['error'])
        evaluate.assert_not_called()

    def test_changed_source_cannot_reuse_original_proof_or_hash(self):
        source=catalog()['variants'][2]['source']
        forged={**self.payload,'source':source,'code_hash':self.accepted['code_hash'],'certificate':self.accepted['proof_certificate'],'valid':True}
        # Keep within the actual request limit; server ignores client proof claims.
        forged['certificate']='care-safe'
        with patch.object(server.engine,'evaluate') as evaluate:
            status,_,_=request(payload=forged)
        self.assertEqual(status,422)
        evaluate.assert_not_called()
        self.assertFalse(server.verification_cache[source]['valid'])
        self.assertTrue(server.verification_cache[DEFAULT_SOURCE]['valid'])

    def test_invalid_state_types_or_fields_are_rejected(self):
        states=[None,[],{},dict(self.state,unexpected=True),{k:v for k,v in self.state.items() if k!='access'}]
        states.extend(dict(self.state,final=value) for value in (1,0,'false',None,[],{}))
        with patch.object(server.engine,'evaluate') as evaluate:
            for state in states:
                with self.subTest(state=state):
                    status,body,_=request(payload={**self.payload,'state':state})
                    self.assertEqual(status,400)
                    self.assertIn('State',body['error'])
            evaluate.assert_not_called()

    def test_invalid_source_payloads_are_rejected(self):
        for payload in ([],None,{},dict(self.payload,source=None),dict(self.payload,source='  '),dict(self.payload,source=12)):
            with self.subTest(payload=payload):
                status,_,_=request(payload=payload)
                self.assertEqual(status,400)

    def test_malformed_json_is_rejected(self):
        for raw in (b'{',b'not-json',b'{"source":}',b'\xff'):
            with self.subTest(raw=raw):
                status,body,_=request(raw=raw)
                self.assertEqual(status,400)
                self.assertIn('error',body)

    def test_unknown_post_and_get_routes_are_not_exposed(self):
        for method in ('POST','GET'):
            status,_,_=request('/api/missing',payload=self.payload,method=method)
            self.assertEqual(status,404)

    def test_static_traversal_and_project_files_are_not_exposed(self):
        for path in ('/../server.py','/%2e%2e/server.py','/static/../server.py','/server.py','/careloop/engine.py','/api/kernel/../../server.py'):
            with self.subTest(path=path):
                status,_,_=request(path,method='GET')
                self.assertEqual(status,404)

    def test_cross_origin_request_is_rejected_before_verification(self):
        with patch.object(server,'checked') as checked:
            status,body,_=request(payload=self.payload,headers={'Origin':'https://unrelated.example'})
        self.assertEqual(status,403)
        self.assertIn('Cross-origin',body['error'])
        checked.assert_not_called()

    def test_request_size_and_empty_body_are_rejected(self):
        for length in ('0','-1',str(server.MAX_REQUEST+1)):
            with self.subTest(length=length):
                status,_,_=request(payload=self.payload,headers={'Content-Length':length})
                self.assertEqual(status,413)
        status,_,_=request(payload=self.payload,headers={'Content-Length':'nonsense'})
        self.assertEqual(status,400)

    def test_non_json_content_is_rejected(self):
        for content_type in ('text/plain','application/x-www-form-urlencoded','multipart/form-data'):
            with self.subTest(content_type=content_type):
                status,_,_=request(payload=self.payload,headers={'Content-Type':content_type})
                self.assertEqual(status,415)

    def test_repeated_exact_source_reuses_verified_result(self):
        server.verification_cache.clear()
        with patch.object(server.engine,'verify_source',wraps=server.engine.verify_source) as verify:
            first=request('/api/verify',payload={'source':DEFAULT_SOURCE})
            second=request('/api/verify',payload={'source':DEFAULT_SOURCE})
            evaluated=request(payload=self.payload)
        self.assertEqual(first[0],200)
        self.assertEqual(second[0],200)
        self.assertEqual(evaluated[0],200)
        self.assertTrue(first[1]['valid'])
        self.assertIs(first[1],second[1])
        verify.assert_called_once_with(DEFAULT_SOURCE)

    def test_checker_exception_fails_closed(self):
        with patch.object(server,'checked',side_effect=RuntimeError('simulated failure')):
            with patch.object(server.engine,'evaluate') as evaluate:
                status,body,_=request(payload=self.payload)
        self.assertEqual(status,500)
        self.assertIn('blocked',body['error'])
        evaluate.assert_not_called()


if __name__=='__main__': unittest.main()
