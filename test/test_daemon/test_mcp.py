"""Tests for the daemon's MCP endpoint."""

import asyncio
import json
from urllib.request import Request, urlopen

import pytest

from nicos.services.daemon import mcp

from test.utils import daemon_addr


def _echo(context, text=''):
    return 'echo: ' + text


def _fail(context):
    raise RuntimeError('boom')


@pytest.fixture
def endpoint():
    schema = {'type': 'object', 'properties': {'text': {'type': 'string'}}}
    return mcp.McpEndpoint(daemon=None, tools=[
        mcp.Tool('echo', 'Echo the text.', schema, _echo),
        mcp.Tool('fail', 'Always fails.', {'type': 'object'}, _fail),
    ])


def _call(endpoint, method, params=None, ident=1):
    message = {'jsonrpc': '2.0', 'id': ident, 'method': method}
    if params is not None:
        message['params'] = params
    return asyncio.run(endpoint.dispatch(message))


def test_initialize(endpoint):
    reply = _call(endpoint, 'initialize', {'protocolVersion': '2025-03-26'})
    result = reply['result']
    assert result['protocolVersion'] == '2025-03-26'
    assert result['serverInfo']['name'] == 'nicos-daemon'
    assert 'get_overview' in result['instructions']
    reply = _call(endpoint, 'initialize', {'protocolVersion': '1999-01-01'})
    assert reply['result']['protocolVersion'] == mcp.PROTOCOL_VERSIONS[0]


def test_notification_gets_no_reply(endpoint):
    message = {'jsonrpc': '2.0', 'method': 'notifications/initialized'}
    assert asyncio.run(endpoint.dispatch(message)) is None


def test_ping_and_list(endpoint):
    assert _call(endpoint, 'ping')['result'] == {}
    tools = _call(endpoint, 'tools/list')['result']['tools']
    assert [tool['name'] for tool in tools] == ['echo', 'fail']
    assert tools[0]['inputSchema']['properties']['text']['type'] == 'string'


def test_call_tool(endpoint):
    reply = _call(endpoint, 'tools/call',
                  {'name': 'echo', 'arguments': {'text': 'hi'}})
    assert reply['result'] == {'content': [{'type': 'text', 'text': 'echo: hi'}],
                               'isError': False}


def test_failing_tool_is_reported_not_raised(endpoint):
    reply = _call(endpoint, 'tools/call', {'name': 'fail'})
    assert reply['result']['isError'] is True
    assert 'RuntimeError: boom' in reply['result']['content'][0]['text']


@pytest.mark.parametrize('method, params, code', [
    ('nosuchmethod', None, mcp.METHOD_NOT_FOUND),
    ('tools/call', {'name': 'nosuchtool'}, mcp.INVALID_PARAMS),
    ('tools/call', {'name': 'echo', 'arguments': [1]}, mcp.INVALID_PARAMS),
    ('ping', [1, 2], mcp.INVALID_PARAMS),
])
def test_errors(endpoint, method, params, code):
    assert _call(endpoint, method, params)['error']['code'] == code


def test_invalid_request(endpoint):
    reply = asyncio.run(endpoint.dispatch({'id': 1, 'method': 'ping'}))
    assert reply['error']['code'] == mcp.INVALID_REQUEST
    reply = asyncio.run(endpoint.dispatch([1, 2]))
    assert reply['error']['code'] == mcp.INVALID_REQUEST


def _post(body):
    request = Request('http://%s/mcp' % daemon_addr, data=body,
                      headers={'Content-Type': 'application/json'})
    with urlopen(request, timeout=5) as response:
        return response.status, response.read()


def test_mcp_over_http(daemon):
    status, body = _post(json.dumps({
        'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
        'params': {'protocolVersion': '2025-06-18'}}).encode())
    assert status == 200
    assert json.loads(body)['result']['serverInfo']['name'] == 'nicos-daemon'

    status, _ = _post(json.dumps({
        'jsonrpc': '2.0', 'method': 'notifications/initialized'}).encode())
    assert status == 202

    status, body = _post(b'{not json')
    assert json.loads(body)['error']['code'] == mcp.PARSE_ERROR
