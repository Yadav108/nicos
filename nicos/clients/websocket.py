"""Synchronous NICOS client over a multiplexed WebSocket."""

import queue
import threading

from websocket import WebSocketTimeoutException, create_connection

from nicos.protocols.daemon import ProtocolError, websocket as wire
from nicos.utils import createThread


class ClientTransport:
    """One reader sorts WebSocket replies and events for the blocking client."""

    def __init__(self):
        self.sock = None
        self.encoding = 'msgpack'
        self.replies = queue.Queue()
        self.events = queue.Queue()
        self.send_lock = threading.Lock()
        self.next_id = 0
        self.pending_id = 0
        self.closed = True

    def connect(self, conndata):
        self.encoding = conndata.wire_format
        if self.encoding not in ('msgpack', 'json'):
            raise ValueError('invalid NICOS wire format')
        scheme = 'wss' if conndata.tls else 'ws'
        url = '%s://%s:%s%s' % (scheme, conndata.host, conndata.port,
                                wire.WS_PATH)
        subprotocol = wire.SUBPROTOCOLS[1 if self.encoding == 'json' else 0]
        self.sock = create_connection(url, timeout=30, subprotocols=[subprotocol])
        self.sock.settimeout(1)
        self.replies = queue.Queue()
        self.events = queue.Queue()
        self.next_id = 0
        self.pending_id = 0
        self.closed = False
        self.reader = createThread('daemon websocket reader', self.read_loop)

    def read_loop(self):
        try:
            while not self.closed:
                try:
                    data = self.sock.recv()
                except WebSocketTimeoutException:
                    continue
                if not data:
                    raise ProtocolError('connection closed')
                if (self.encoding == 'json') != isinstance(data, str):
                    raise ProtocolError('wrong WebSocket frame type')
                message = wire.decode(data, self.encoding)
                if isinstance(message, (wire.Banner, wire.Reply)):
                    self.replies.put(message)
                elif isinstance(message, wire.Event):
                    self.events.put(message)
                elif isinstance(message, wire.EventError):
                    self.events.put(message)
                else:
                    raise ProtocolError('unexpected server message')
        except Exception as err:
            if not self.closed:
                self.replies.put(err)
                self.events.put(err)

    def disconnect(self):
        self.closed = True
        sock, self.sock = self.sock, None
        if sock:
            sock.close()
        error = ProtocolError('connection closed')
        self.replies.put(error)
        self.events.put(error)

    def send_command(self, cmdname, args):
        self.next_id += 1
        self.pending_id = self.next_id
        message = wire.Command(self.pending_id, cmdname,
                               wire.pack_payload(wire.command_args(args),
                                                 self.encoding))
        data = wire.encode(message, self.encoding)
        with self.send_lock:
            if self.encoding == 'json':
                self.sock.send(data)
            else:
                self.sock.send_binary(data)

    def recv_reply(self):
        message = self.replies.get()
        if isinstance(message, Exception):
            raise message
        if isinstance(message, wire.Banner):
            if self.pending_id:
                raise ProtocolError('unexpected banner')
            return True, wire.unpack_payload(message.payload, self.encoding)
        if not isinstance(message, wire.Reply) or message.id != self.pending_id:
            raise ProtocolError('reply ID mismatch')
        return message.ok, wire.unpack_payload(message.payload, self.encoding,
                                               allow_pickle=True)

    def recv_event(self):
        message = self.events.get()
        if isinstance(message, Exception):
            raise message
        if isinstance(message, wire.EventError):
            return 'protocol_error', 'Event %s unavailable: %s' % (
                message.name, message.reason), []
        return (message.name,
                wire.unpack_payload(message.payload, self.encoding,
                                    allow_pickle=True),
                [memoryview(blob) for blob in message.blobs])
