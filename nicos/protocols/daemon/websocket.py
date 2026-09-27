"""Messages for the HTTP/WebSocket daemon protocol."""

import base64
import pickle
from typing import Any, Union

import msgspec

DEFAULT_PORT = 1301
PROTO_VERSION = 1
WS_PATH = '/api/v1/daemon'
SUBPROTOCOLS = ('nicos.msgpack.v1', 'nicos.json.v1')


class Payload(msgspec.Struct):
    kind: str
    data: Any = None


class Banner(msgspec.Struct, tag='banner'):
    payload: Payload


class Command(msgspec.Struct, tag='command'):
    id: int
    name: str
    args: Payload


class Reply(msgspec.Struct, tag='reply'):
    id: int
    ok: bool
    payload: Payload


class Event(msgspec.Struct, tag='event'):
    name: str
    payload: Payload
    blobs: list[bytes]


class EventError(msgspec.Struct, tag='event_error'):
    name: str
    reason: str


Message = Union[Banner, Command, Reply, Event, EventError]


# Exact builtin types are intentional: subclasses may need the pickle fallback.
def _native(value, json_mode):
    if value.__class__ is int and not json_mode and \
            not -(2**63) <= value < 2**64:
        raise TypeError('integer exceeds MessagePack range')
    if value is None or value.__class__ in (bool, int, float, str):
        return value
    if value.__class__ is bytes:
        if json_mode:
            raise TypeError('bytes require a typed payload')
        return value
    if value.__class__ is tuple:
        return [_native(item, json_mode) for item in value]
    if value.__class__ is list:
        return [_native(item, json_mode) for item in value]
    if value.__class__ is dict and all(key.__class__ is str for key in value):
        return {key: _native(item, json_mode) for key, item in value.items()}
    raise TypeError('unsupported payload type %s' % type(value).__name__)


def command_args(args):
    """Normalize tuple containers without changing binary command data."""
    def convert(value):
        if isinstance(value, (tuple, list)):
            return [convert(item) for item in value]
        if isinstance(value, dict):
            return {key: convert(item) for key, item in value.items()}
        return value
    return convert(args)


def pack_payload(value, encoding):
    """Keep Python-only values in a clearly marked pickle payload."""
    if value.__class__ is bytes:
        if encoding == 'json':
            return Payload('bytes', base64.b64encode(value).decode('ascii'))
        return Payload('native', value)
    try:
        return Payload('native', _native(value, encoding == 'json'))
    except TypeError:
        if encoding == 'json':
            raise
        return Payload('pickle', pickle.dumps(value, protocol=4))


def unpack_payload(payload, encoding, allow_pickle=False):
    if payload.kind == 'native':
        return payload.data
    if payload.kind == 'bytes' and encoding == 'json':
        return base64.b64decode(payload.data, validate=True)
    if payload.kind == 'pickle' and encoding == 'msgpack' and allow_pickle:
        return pickle.loads(payload.data)
    raise ValueError('unsupported payload encoding %r' % payload.kind)


def encode(message, encoding):
    if encoding == 'json':
        return msgspec.json.encode(message).decode('utf-8')
    return msgspec.msgpack.encode(message)


def decode(data, encoding):
    if encoding == 'json':
        return msgspec.json.decode(data, type=Message)
    return msgspec.msgpack.decode(data, type=Message)
