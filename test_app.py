import hashlib
import hmac
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from http.server import ThreadingHTTPServer

from app import Service, make_handler
from assistant_flow import advance

CATALOG = [{'model': 'Corolla', 'year_from': 2015, 'year_to': 2017,
            'image_url': 'https://example.com/corolla.jpg'}]


class FlowTests(unittest.TestCase):
    def test_only_ask_missing_year(self):
        state, replies = advance({}, {'model': 'Corolla'}, CATALOG)
        self.assertIn('Qual é o ano', replies[0]['text'])

    def test_complete_sale_then_pause_without_booking(self):
        state, replies = advance({}, {'model': 'Corolla', 'year': 2016}, CATALOG)
        self.assertIn('image', replies[0])
        state, replies = advance(state, {'intent': 'confirm'}, CATALOG)
        self.assertIn('R$269', replies[0]['text'])
        self.assertIn('4 vezes sem juros', replies[0]['text'])
        state, replies = advance(state, {'intent': 'accept'}, CATALOG)
        self.assertIn('cidade', replies[0]['text'])
        state, replies = advance(state, {'city': 'Barueri', 'neighborhood': 'Centro'}, CATALOG)
        self.assertIn('sexta-feira após as 12h', replies[0]['text'])
        state, replies = advance(state, {'preferred_day': 'sábado'}, CATALOG)
        self.assertTrue(state['paused'])
        self.assertIn('será confirmado por ele', replies[0]['text'])
        self.assertEqual(advance(state, {'intent': 'price'}, CATALOG)[1], [])

    def test_unknown_or_ambiguous_vehicle_needs_photo(self):
        for catalog in ([], CATALOG + CATALOG):
            state, replies = advance({}, {'model': 'Corolla', 'year': 2016}, catalog)
            self.assertIn('foto do volante atual', replies[0]['text'])
            state, replies = advance(state, {'has_image': True}, catalog)
            self.assertTrue(state['paused'])

    def test_wrong_wheel_cannot_be_confirmed_accidentally(self):
        state, _ = advance({}, {'model': 'Corolla', 'year': 2016}, CATALOG)
        state, _ = advance(state, {'intent': 'reject'}, CATALOG)
        state, replies = advance(state, {'intent': 'confirm'}, CATALOG)
        self.assertNotIn('R$269', replies[0]['text'])
        self.assertFalse(state.get('wheel_confirmed', False))

    def test_vehicle_change_invalidates_confirmation(self):
        state = {'model': 'Corolla', 'year': 2016, 'vehicle_key': 'corolla:2016',
                 'wheel_confirmed': True, 'offered': True, 'accepted': True}
        state, replies = advance(state, {'year': 2020}, CATALOG)
        self.assertFalse(state.get('wheel_confirmed', False))
        self.assertFalse(state.get('accepted', False))
        self.assertIn('foto', replies[0]['text'])

    def test_human_and_opt_out_pause(self):
        for intent in ('human', 'stop'):
            state, _ = advance({}, {'intent': intent}, CATALOG)
            self.assertTrue(state['paused'])


class WebhookTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config = {'phone_id': '12345', 'app_secret': 'fixture-signature-secret',
                       'verify_token': 'fixture-verify', 'admin_token': 'fixture-admin'}
        self.service = Service(str(Path(self.tmp.name) / 'test.sqlite3'), CATALOG, self.config)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(self.service))
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.tmp.cleanup()

    def payload(self, message_id='m1', kind='text', age=0):
        return {'object': 'whatsapp_business_account', 'entry': [{'changes': [{'value': {
            'metadata': {'phone_number_id': '12345'}, 'messages': [{
                'id': message_id, 'from': '5511000000000', 'type': kind,
                'timestamp': str(int(time.time() - age)), 'text': {'body': 'Corolla 2016'}}]}}]}]}

    def post(self, payload, signature=True):
        body = json.dumps(payload).encode()
        digest = hmac.new(self.config['app_secret'].encode(), body, hashlib.sha256).hexdigest()
        return urlopen(Request(self.url + '/webhook', data=body, headers={
            'X-Hub-Signature-256': 'sha256=' + digest if signature else 'bad'}), timeout=3)

    def test_verification_and_health(self):
        with urlopen(self.url + '/webhook?hub.mode=subscribe&hub.verify_token=fixture-verify&hub.challenge=987') as r:
            self.assertEqual(r.read(), b'987')
        with self.assertRaises(HTTPError) as ctx:
            urlopen(self.url + '/webhook?hub.mode=subscribe&hub.verify_token=wrong&hub.challenge=987')
        self.assertEqual(ctx.exception.code, 403)
        with urlopen(self.url + '/health') as r:
            self.assertEqual(json.load(r)['status'], 'ok')

    def test_reject_unsigned_and_deduplicate_signed_events(self):
        with self.assertRaises(HTTPError) as ctx:
            self.post(self.payload(), signature=False)
        self.assertEqual(ctx.exception.code, 403)
        for _ in range(2):
            with self.post(self.payload()) as r:
                self.assertEqual(r.status, 200)
        with self.service.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM inbox').fetchone()[0], 1)

    def test_worker_receives_and_sends_photo_once(self):
        self.service.extract = Mock(return_value={'model': 'Corolla', 'year': 2016})
        self.service.send = Mock()
        self.service.enqueue(self.payload())
        self.assertTrue(self.service.process_one())
        self.service.enqueue(self.payload())
        self.assertFalse(self.service.process_one())
        self.service.send.assert_called_once()
        self.assertIn('image', self.service.send.call_args.args[1])

    def test_ambiguous_delivery_requires_review_and_no_retry(self):
        self.service.extract = Mock(return_value={'model': 'Corolla', 'year': 2016})
        self.service.send = Mock(side_effect=TimeoutError())
        self.service.enqueue(self.payload())
        self.service.process_one()
        self.service.enqueue(self.payload('m2'))
        self.service.process_one()
        self.service.send.assert_called_once()
        self.assertTrue(self.service.handoffs()[0]['state']['paused'])

    def test_expired_message_is_not_sent(self):
        self.service.send = Mock()
        self.service.extract = Mock()
        self.service.enqueue(self.payload(age=25 * 3600))
        self.service.process_one()
        self.service.send.assert_not_called()
        self.service.extract.assert_not_called()
        self.assertTrue(self.service.handoffs())

    def test_audio_handoff_and_admin_auth(self):
        self.service.send = Mock()
        self.service.enqueue(self.payload(kind='audio'))
        self.service.process_one()
        with self.assertRaises(HTTPError) as ctx:
            urlopen(self.url + '/handoffs')
        self.assertEqual(ctx.exception.code, 401)
        with urlopen(Request(self.url + '/handoffs', headers={'Authorization': 'Bearer fixture-admin'})) as r:
            self.assertEqual(len(json.load(r)['handoffs']), 1)
        with urlopen(self.url + '/panel') as r:
            self.assertIn(b'Gabriel Volantes', r.read())

    def test_process_restart_does_not_resend_uncertain_job(self):
        self.service.enqueue(self.payload())
        with self.service.db() as db:
            db.execute("UPDATE inbox SET status='processing'")
        restarted = Service(self.service.db_path, CATALOG, self.config)
        self.assertTrue(restarted.handoffs()[0]['state']['paused'])
        self.assertFalse(restarted.process_one())


if __name__ == '__main__':
    unittest.main()
