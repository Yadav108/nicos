"""HTTP and browser-style JSON WebSocket coverage for the daemon."""

import json
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.request import urlopen

import pytest
from websocket import ABNF, WebSocketTimeoutException, create_connection

from nicos.clients import websocket as client_websocket
from nicos.protocols.daemon import ProtocolError, websocket as wire
from nicos.protocols.daemon.websocket import WS_PATH
from nicos.services.daemon import webserver

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


def test_server_closes_client_with_full_outgoing_queue(monkeypatch):
    scheduled = []
    loop = SimpleNamespace(is_running=lambda: False,
                           call_soon_threadsafe=lambda *args: scheduled.append(args))
    daemon = SimpleNamespace(_controller=None, log=Mock())
    server = SimpleNamespace(daemon=daemon, loop=loop)
    handler = webserver.Handler(server, Mock(), [], 'msgpack')
    message = wire.EventError('status', 'unavailable')
    size = len(wire.encode(message, 'msgpack'))
    monkeypatch.setattr(webserver, 'OUTGOING_BYTES_LIMIT', size)

    handler.enqueue(message)
    assert handler.out_bytes == size
    assert len(scheduled) == 1
    handler.enqueue(message)
    assert handler.closed
    assert handler.out_bytes == size
    assert len(scheduled) == 1


def test_network_delivery_error_does_not_escape_event_emit():
    daemon = SimpleNamespace(log=Mock())
    server = webserver.Server(daemon, ('localhost', 0))
    broken = Mock()
    broken.emit.side_effect = OSError('socket disappeared')
    healthy = Mock()
    server.handlers.update((broken, healthy))

    server.emit('status', {'state': 'idle'}, [])

    broken.close.assert_called_once()
    healthy.emit.assert_called_once_with('status', {'state': 'idle'}, [])


def test_client_event_queue_is_bounded_and_cleared_on_failure(monkeypatch):
    transport = client_websocket.ClientTransport()
    transport.closed = False
    transport.sock = Mock()
    transport.sock.recv_data.return_value = (
        ABNF.OPCODE_BINARY, wire.encode(wire.EventError('status', 'new'),
                                        'msgpack'))
    monkeypatch.setattr(client_websocket, 'EVENT_BYTES_LIMIT', 10)
    event = wire.EventError('status', 'unavailable')

    transport.queue_event(event, 10)
    with pytest.raises(ProtocolError, match='event queue full'):
        transport.queue_event(event, 1)
    transport.read_loop()

    transport.sock.close.assert_called_once()
    assert transport.event_bytes == 0
    with pytest.raises(ProtocolError, match='event queue full'):
        transport.recv_event()


def test_client_detects_unresponsive_connection(monkeypatch):
    transport = client_websocket.ClientTransport()
    transport.closed = False
    transport.sock = Mock()
    transport.sock.recv_data.side_effect = WebSocketTimeoutException()
    ticks = iter((0, 31, 62))
    monkeypatch.setattr(client_websocket, 'monotonic', lambda: next(ticks))

    transport.read_loop()

    transport.sock.ping.assert_called_once()
    with pytest.raises(ProtocolError, match='did not answer WebSocket ping'):
        transport.recv_event()
