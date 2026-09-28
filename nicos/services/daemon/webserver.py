"""HTTP server and WebSocket connection for the execution daemon."""

import asyncio
import queue
import socket
import threading
from urllib.parse import urlsplit

import msgspec
from aiohttp import WSMsgType, web

from nicos.protocols.daemon import CloseConnection, ProtocolError, \
    websocket as wire
from nicos.services.daemon.handler import ConnectionHandler
from nicos.utils import createThread

OUTGOING_BYTES_LIMIT = 100 * 1024 * 1024
WRITE_TIMEOUT = 60


class Server:
    """Serve HTTP routes and authenticated daemon WebSockets on one port."""

    def __init__(self, daemon, address):
        self.daemon = daemon
        self.address = address
        self.handlers = set()
        self.lock = threading.Lock()
        self.next_ident = 0
        self.loop = None
        self.runner = None

    def start(self, interval):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        app = web.Application()
        app.router.add_get(wire.WS_PATH, self.websocket)
        app.router.add_get('/healthz', self.health)
        self.runner = web.AppRunner(app)

        async def serve():
            await self.runner.setup()
            host, port = self.address
            site = web.TCPSite(self.runner, socket.gethostbyname(host), port)
            await site.start()

        try:
            self.loop.run_until_complete(serve())
            self.loop.run_forever()
        finally:
            self.loop.run_until_complete(self._shutdown())
            self.loop.close()
            self.loop = None

    async def health(self, request):
        return web.Response(text='ok')

    async def websocket(self, request):
        origin = request.headers.get('Origin')
        if origin and urlsplit(origin).netloc != request.host:
            raise web.HTTPForbidden(text='cross-origin WebSocket denied')
        host = request.remote or ''
        try:
            names = [socket.gethostbyaddr(host)[0], host]
        except (OSError, socket.herror):
            names = [host]
        if self.daemon.trustedhosts and not any(
                name in self.daemon.trustedhosts for name in names):
            raise web.HTTPForbidden(text='permission denied')
        offered = [part.strip() for part in
                   request.headers.get('Sec-WebSocket-Protocol', '').split(',')]
        if not any(proto in offered for proto in wire.SUBPROTOCOLS):
            raise web.HTTPBadRequest(text='NICOS WebSocket subprotocol required')
        ws = web.WebSocketResponse(protocols=wire.SUBPROTOCOLS,
                                   heartbeat=30,
                                   max_msg_size=128 * 1024 * 1024)
        await ws.prepare(request)
        encoding = 'json' if ws.ws_protocol == wire.SUBPROTOCOLS[1] else 'msgpack'
        handler = Handler(self, ws, names, encoding)
        with self.lock:
            self.next_ident += 1
            handler.setIdent(self.next_ident)
            self.handlers.add(handler)
        handler.worker = createThread('daemon handler %d' % handler.ident,
                                      handler.handle_loop)
        writer = asyncio.create_task(handler.write_loop())
        try:
            async for msg in ws:
                if msg.type not in (WSMsgType.BINARY, WSMsgType.TEXT):
                    continue
                if (encoding == 'json') != (msg.type == WSMsgType.TEXT):
                    raise ProtocolError('wrong WebSocket frame type')
                command = wire.decode(msg.data, encoding)
                if not isinstance(command, wire.Command):
                    raise ProtocolError('expected command')
                if command.id <= 0:
                    raise ProtocolError('invalid request ID')
                if handler.awaiting_reply:
                    raise ProtocolError('command already pending')
                if command.name not in handler.commands:
                    handler.reply_error(command.id, 'unknown command')
                    continue
                args = wire.unpack_payload(command.args, encoding,
                                           allow_pickle=handler.authenticated)
                if not isinstance(args, list):
                    raise ProtocolError('command arguments must be a list')
                handler.awaiting_reply = True
                handler.commands_in.put((command.id, command.name, args))
        except (ProtocolError, ValueError, TypeError,
                msgspec.DecodeError) as err:
            handler.close()
            handler.log.warning('protocol error: %s', err)
        finally:
            handler.close()
            with self.lock:
                self.handlers.discard(handler)
            await writer
            await ws.close()
        return ws

    def emit(self, event, data, blobs, handler=None):
        with self.lock:
            targets = [handler] if handler else list(self.handlers)
        for target in targets:
            try:
                target.emit(event, data, blobs)
            except Exception:
                # Event delivery must never interrupt the measurement thread.
                try:
                    target.close()
                except Exception:
                    pass
                self.daemon.log.exception('closing failed daemon client')

    def stop(self):
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)

    async def _shutdown(self):
        with self.lock:
            handlers = list(self.handlers)
        for handler in handlers:
            handler.close()
        if self.runner:
            await self.runner.cleanup()


class Handler(ConnectionHandler):
    """Bridge the blocking NICOS command handler to one WebSocket."""

    from nicos.services.daemon.handler import command_wrappers as commands

    def __init__(self, server, ws, names, encoding):
        super().__init__(server.daemon)
        self.server = server
        self.ws = ws
        self.clientnames = names
        self.encoding = encoding
        self.commands_in = queue.Queue()
        self.outgoing = asyncio.Queue()
        self.out_bytes = 0
        self.out_lock = threading.Lock()
        self.request_id = 0
        self.awaiting_reply = False
        self.authenticated = False
        self.closed = False
        self.close_lock = threading.Lock()

    def get_version(self):
        return wire.PROTO_VERSION

    def handle_loop(self):
        try:
            self.handle()
        except CloseConnection:
            pass
        except Exception:
            self.close()
            self.log.exception('unexpected handler error')
        finally:
            self.close()

    def recv_command(self):
        item = self.commands_in.get()
        if item is None:
            raise CloseConnection
        self.request_id, name, args = item
        return name, args

    def send_ok_reply(self, payload):
        try:
            packed = wire.pack_payload(payload, self.encoding)
        except Exception as err:
            self.send_error_reply(str(err))
            return
        if self.request_id == 0:
            self.enqueue(wire.Banner(packed))
        else:
            self.enqueue(wire.Reply(self.request_id, True, packed))

    def send_error_reply(self, reason):
        self.enqueue(wire.Reply(self.request_id, False,
                                wire.pack_payload(reason, self.encoding)))

    def reply_error(self, request_id, reason):
        self.enqueue(wire.Reply(request_id, False,
                                wire.pack_payload(reason, self.encoding)))

    def emit(self, event, data, blobs):
        if not self.authenticated or event in self.event_mask or self.closed:
            return
        try:
            packed = wire.pack_payload(data, self.encoding)
            message = wire.Event(event, packed, [bytes(blob) for blob in blobs])
        except Exception as err:
            message = wire.EventError(event, str(err))
        self.enqueue(message)

    def enqueue(self, message):
        if self.closed or not self.server.loop:
            return
        encoded = wire.encode(message, self.encoding)
        with self.out_lock:
            if self.out_bytes + len(encoded) > OUTGOING_BYTES_LIMIT:
                overflow = True
            else:
                overflow = False
                self.out_bytes += len(encoded)
        if overflow:
            self.close()
            self.log.warning('outgoing queue full, closing connection')
            return
        try:
            self.server.loop.call_soon_threadsafe(self._enqueue_encoded,
                                                  encoded,
                                                  isinstance(message, wire.Reply))
        except RuntimeError:
            with self.out_lock:
                self.out_bytes -= len(encoded)

    def _enqueue_encoded(self, encoded, is_reply):
        if self.closed:
            with self.out_lock:
                self.out_bytes -= len(encoded)
            return
        if is_reply:
            self.awaiting_reply = False
        self.outgoing.put_nowait(encoded)

    async def write_loop(self):
        while True:
            data = await self.outgoing.get()
            if data is None:
                break
            try:
                if self.encoding == 'json':
                    await asyncio.wait_for(self.ws.send_str(data), timeout=WRITE_TIMEOUT)
                else:
                    await asyncio.wait_for(self.ws.send_bytes(data), timeout=WRITE_TIMEOUT)
            except Exception:
                self.close()
                break
            finally:
                with self.out_lock:
                    self.out_bytes -= len(data)

    def close(self):
        with self.close_lock:
            if self.closed:
                return
            self.closed = True
        self.commands_in.put(None)
        loop = self.server.loop
        if loop and loop.is_running():
            try:
                loop.call_soon_threadsafe(self._close_on_loop)
            except RuntimeError:
                pass

    def _close_on_loop(self):
        self.outgoing.put_nowait(None)
        asyncio.create_task(self._close_socket())

    async def _close_socket(self):
        try:
            await self.ws.close()
        except (OSError, ConnectionError, RuntimeError):
            pass
