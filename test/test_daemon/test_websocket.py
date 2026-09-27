"""HTTP and browser-style JSON WebSocket coverage for the daemon."""

import json
from urllib.request import urlopen

from websocket import create_connection

from nicos.protocols.daemon.websocket import WS_PATH

from test.utils import daemon_addr


def _request(ws, ident, name, args):
    ws.send(json.dumps({
        'type': 'command', 'id': ident, 'name': name,
        'args': {'kind': 'native', 'data': args},
    }))
    while True:
        message = json.loads(ws.recv())
        if message['type'] == 'reply' and message['id'] == ident:
            return message


def test_http_and_json_websocket(daemon):
    with urlopen('http://%s/healthz' % daemon_addr, timeout=5) as response:
        assert response.read() == b'ok'

    ws = create_connection('ws://%s%s' % (daemon_addr, WS_PATH), timeout=5,
                           subprotocols=['nicos.json.v1'])
    try:
        banner = json.loads(ws.recv())
        assert banner['type'] == 'banner'
        assert banner['payload']['data']['protocol_version'] == 1

        reply = _request(ws, 1, 'authenticate', [dict(login='guest', passwd='',
                                                      display='')])
        assert reply['ok']
        assert reply['payload']['data']['user_level'] is not None

        reply = _request(ws, 2, 'getversion', [])
        assert reply['ok']
        assert isinstance(reply['payload']['data'], str)

        reply = _request(ws, 3, 'eval', ["b'abc'", False])
        assert reply['ok']
        assert reply['payload'] == {'kind': 'bytes', 'data': 'YWJj'}

        reply = _request(ws, 4, 'eval', ['int', False])
        assert not reply['ok']
        assert 'unsupported payload type type' in reply['payload']['data']
    finally:
        ws.close()
