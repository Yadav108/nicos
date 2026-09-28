"""Synchronous NICOS client over a multiplexed WebSocket."""

import queue
import threading
from time import monotonic

from websocket import ABNF, WebSocketTimeoutException, create_connection

from nicos.protocols.daemon import ProtocolError, websocket as wire
from nicos.utils import createThread

EVENT_BYTES_LIMIT = 100 * 1024 * 1024
PING_INTERVAL = 30
PONG_TIMEOUT = 30


class ClientTransport:
    """One reader sorts WebSocket replies and events for the blocking client."""

    def __init__(self):
        self.sock = None
        self.encoding = 'msgpack'
        self.replies = queue.Queue()
        self.events = queue.Queue()
        self.event_bytes = 0
        self.event_lock = threading.Lock()
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
        self.event_bytes = 0
        self.next_id = 0
        self.pending_id = 0
        self.closed = False
        self.reader = createThread('daemon websocket reader', self.read_loop)

    def read_loop(self):
        sock = self.sock
        last_ping = monotonic()
        ping_sent_at = None
        try:
            while not self.closed and self.sock is sock:
                try:
                    opcode, data = sock.recv_data(control_frame=True)
                except WebSocketTimeoutException:
                    pass
                else:
                    if self.sock is not sock:
                        return
                    if opcode == ABNF.OPCODE_PONG:
                        ping_sent_at = None
                    elif opcode == ABNF.OPCODE_CLOSE:
                        raise ProtocolError('connection closed')
                    elif opcode in (ABNF.OPCODE_BINARY, ABNF.OPCODE_TEXT):
                        size = len(data)
                        if (self.encoding == 'json') != \
                                (opcode == ABNF.OPCODE_TEXT):
                            raise ProtocolError('wrong WebSocket frame type')
                        if opcode == ABNF.OPCODE_TEXT:
                            data = data.decode('utf-8') if isinstance(data, bytes) else data
                        message = wire.decode(data, self.encoding)
                        if isinstance(message, (wire.Banner, wire.Reply)):
                            self.replies.put(message)
                        elif isinstance(message, (wire.Event, wire.EventError)):
                            self.queue_event(message, size)
                        else:
                            raise ProtocolError('unexpected server message')
                now = monotonic()
                if ping_sent_at is not None and now - ping_sent_at >= PONG_TIMEOUT:
                    raise ProtocolError('daemon did not answer WebSocket ping')
                if ping_sent_at is None and now - last_ping >= PING_INTERVAL:
                    with self.send_lock:
                        sock.ping()
                    ping_sent_at = last_ping = now
        except Exception as err:
            if not self.closed and self.sock is sock:
                self.closed = True
                try:
                    sock.close()
                except OSError:
                    pass
                self.replies.put(err)
                self._clear_events()
                self.events.put((0, err))

    def queue_event(self, message, size):
        with self.event_lock:
            if self.closed:
                return
            if self.event_bytes + size > EVENT_BYTES_LIMIT:
                raise ProtocolError('event queue full')
            self.event_bytes += size
            self.events.put((size, message))

    def _clear_events(self):
        with self.event_lock:
            while True:
                try:
                    self.events.get_nowait()
                except queue.Empty:
                    break
            self.event_bytes = 0

    def disconnect(self):
        self.closed = True
        sock, self.sock = self.sock, None
        if sock:
            sock.close()
        error = ProtocolError('connection closed')
        self.replies.put(error)
        self._clear_events()
        self.events.put((0, error))

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
        size, message = self.events.get()
        with self.event_lock:
            self.event_bytes = max(0, self.event_bytes - size)
        if isinstance(message, Exception):
            raise message
        if isinstance(message, wire.EventError):
            return 'protocol_error', 'Event %s unavailable: %s' % (
                message.name, message.reason), []
        return (message.name,
                wire.unpack_payload(message.payload, self.encoding,
                                    allow_pickle=True),
                [memoryview(blob) for blob in message.blobs])
