"""Tests for the daemon's MCP tools."""

import json
import re
import time
from types import SimpleNamespace
from urllib.request import Request, urlopen

import pytest

from nicos.core.params import oneof
from nicos.core.status import BUSY, OK
from nicos.protocols.daemon import STATUS_IDLE, STATUS_RUNNING
from nicos.services.daemon import mcp_tools
from nicos.services.daemon.mcp import INSTRUCTIONS, McpContext, ToolError

from test.test_daemon.test_client import load_setup
from test.utils import daemon_addr

ALL_VISIBLE = ('metadata', 'namespace', 'devlist')


class FakeDevice:
    def __init__(self, description='', unit='', visibility=ALL_VISIBLE):
        self.description = description
        self.unit = unit
        self.visibility = visibility

    def format(self, value):
        return '%.3f' % value


class FakeCache:
    """Local cache DB; get_explicit says every value is 30 s old."""

    def __init__(self, db):
        self.db = dict(db)

    def query_db(self, query):
        query = set(query)
        return [(key, value) for key, value in self.db.items()
                if key in query]

    def get_explicit(self, dev, key, default=None):
        return (time.time() - 30, 0,
                self.db.get('%s/%s' % (dev.lower(), key), default))


CACHE_DB = {
    'motor1/value': 12.3,
    'motor1/status': (OK, 'idle'),
    'motor1/target': 12.3,
    'motor1/userlimits': (-10, 90),
    'motor1/abslimits': (-180, 180),
    'motor1/password': 'secret123',
    'temp1/value': 4.2,
    'temp1/status': (BUSY, 'ramping'),
}


def scan(dev, *args):
    """Scan a device.

    Longer explanation of the scan command.
    """


def hidden_cmd():
    """Not for users."""


scan.is_usercommand = True
hidden_cmd.is_usercommand = True
hidden_cmd.is_hidden = True


def _context(status=STATUS_IDLE, script=None):
    devices = {
        'motor1': FakeDevice('Sample rotation', 'deg'),
        'temp1': FakeDevice('Sample temperature', 'K'),
        'hidden': FakeDevice('Low-level', 'V', visibility=('metadata',)),
    }
    exported = [('scan', scan), ('sc', scan), ('hidden_cmd', hidden_cmd)] + \
        list(devices.items())
    setup_info = {
        'base': {'description': 'Base setup',
                 'devices': {'motor1': None, 'hidden': None}},
        'extra': {'description': 'Extra setup', 'devices': {'temp1': None}},
    }
    session = SimpleNamespace(
        devices=devices,
        cache=FakeCache(CACHE_DB),
        loaded_setups={'base', 'extra'},
        getSetupInfo=lambda: setup_info,
        getExportedObjects=lambda: iter(exported),
        instrument=SimpleNamespace(instrument='TESTINSTR'),
        experiment=SimpleNamespace(proposal='p123', title='Test experiment',
                                   scriptpath='/data/p123/scripts',
                                   detlist=['det1', 'det2'], envlist=[]),
    )
    controller = SimpleNamespace(status=status, current_script=script,
                                 lineno=7)
    return McpContext(session, SimpleNamespace(_controller=controller))


def test_overview():
    text = mcp_tools.get_overview(_context())
    assert text.startswith('# get_overview')
    assert 'truncated: no' in text
    assert '## rules' in text
    assert 'never start scripts' in text
    assert 'instrument: TESTINSTR' in text
    assert 'proposal: p123 "Test experiment"' in text
    assert 'detectors (used by scans and count): det1, det2' in text
    assert 'environment (read at every scan point): (none)' in text
    # no scripts folder until there is a tool that writes scripts
    assert 'scripts/model' not in text
    assert 'daemon: idle' in text
    assert 'setups (2): base, extra' in text
    assert 'more setups' not in text
    assert 'devices: 2 user-visible' in text
    assert 'commands: 1 ' in text


def test_overview_running_script():
    script = SimpleNamespace(name='myscan.py')
    text = mcp_tools.get_overview(_context(STATUS_RUNNING, script))
    assert "daemon: running 'myscan.py', line 7" in text


def test_devices_index():
    text = mcp_tools.get_info(_context(), section='devices')
    assert 'shown 2 of 2 | truncated: no' in text
    assert '## setup base' in text
    assert 'motor1  device  deg  Sample rotation' in text
    assert 'temp1  device  K  Sample temperature' in text
    assert 'hidden' not in text
    assert text.index('## setup base') < text.index('motor1') < \
        text.index('## setup extra') < text.index('temp1')


def test_devices_pattern():
    text = mcp_tools.get_info(_context(), section='devices',
                              name='temp*')
    assert 'temp1' in text
    assert 'motor1' not in text


def test_device_detail():
    text = mcp_tools.get_info(_context(), section='devices',
                              name='MOTOR1')
    # same as get_device_info for this device
    assert text == mcp_tools.get_device_info(_context(), devices=['motor1'])
    assert '## motor1' in text
    assert 'setup: base' in text
    assert 'description: Sample rotation' in text
    assert 'value: 12.300 deg' in text
    text = mcp_tools.get_info(_context(), section='devices',
                              name='hidden')
    assert 'hidden from the user device list' in text


def test_device_detail_not_readable():
    context = _context()
    context.session.devices['Exp'] = SimpleNamespace(
        description='experiment object', visibility=ALL_VISIBLE)
    text = mcp_tools.get_device_info(context, devices=['Exp'])
    assert 'description: experiment object' in text
    assert 'value: - (device is not readable)' in text
    assert 'Exp' not in mcp_tools.get_device_info(context)


def test_unknown_device_suggests_names():
    with pytest.raises(ToolError, match="unknown device 'motr1'; "
                                        "did you mean: motor1"):
        mcp_tools.get_info(_context(), section='devices', name='motr1')


def test_commands_index_and_detail():
    text = mcp_tools.get_info(_context(), section='commands')
    assert 'scan(dev, *args)  Scan a device.' in text
    assert 'hidden_cmd' not in text
    assert 'sc(' not in text
    text = mcp_tools.get_info(_context(), section='commands',
                              name='scan')
    assert 'Longer explanation of the scan command.' in text
    assert text.splitlines()[1] == '# truncated: no'


def test_setups():
    text = mcp_tools.get_info(_context(), section='setups')
    assert 'base  Base setup' in text
    text = mcp_tools.get_info(_context(), section='setups',
                              name='extra')
    assert 'description: Extra setup' in text
    assert 'temp1' in text


def test_setups_available_but_not_loaded():
    context = _context()
    context.session.getSetupInfo().update({
        'magnet': {'group': 'optional', 'description': 'Magnet'},
        'Cryo': {'group': 'basic', 'description': 'Cryostat'},
        'daemon': {'group': 'special', 'description': 'Daemon'},
        'motors': {'group': 'lowlevel', 'description': 'Motors'},
        'broken': None,
    })
    text = mcp_tools.get_info(context, section='setups')
    assert 'shown 4 of 4' in text
    assert text.index('## loaded') < text.index('base  Base setup') < \
        text.index('## available, not loaded') < \
        text.index('Cryo  Cryostat') < text.index('magnet  Magnet')
    for hidden in ('daemon', 'motors', 'broken'):
        assert hidden not in text
    # patterns ignore case and apply to both groups
    text = mcp_tools.get_info(context, section='setups', name='MAG*')
    assert 'magnet  Magnet' in text
    assert '## loaded' not in text
    assert 'base' not in text
    text = mcp_tools.get_overview(context)
    assert 'more setups: 2 available, not loaded -> ' \
        'get_info(section="setups")' in text


def test_bad_arguments():
    with pytest.raises(ToolError, match='unknown section'):
        mcp_tools.get_info(_context(), section='nosuch')
    with pytest.raises(ToolError, match='section is required'):
        mcp_tools.get_info(_context(), name='scan')


def test_format_reply_truncates():
    lines = ['x' * 99] * 1000
    text = mcp_tools.format_reply('title', lines, 'narrow it')
    assert len(text) <= mcp_tools.REPLY_LIMIT
    assert 'truncated: yes' in text
    assert '# hint: narrow it' in text


def _call_tool(name, arguments):
    body = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                       'params': {'name': name, 'arguments': arguments}})
    request = Request('http://%s/mcp' % daemon_addr, data=body.encode(),
                      headers={'Content-Type': 'application/json'})
    with urlopen(request, timeout=10) as response:
        result = json.loads(response.read())['result']
    text = result['content'][0]['text']
    assert len(text) <= mcp_tools.REPLY_LIMIT
    return result['isError'], text


def test_overview_and_info_on_daemon(client):
    load_setup(client, 'daemontest')

    is_error, text = _call_tool('get_overview', {})
    assert not is_error, text
    assert 'instrument: INSTR' in text
    assert 'daemontest' in text

    is_error, text = _call_tool('get_info', {'section': 'devices'})
    assert not is_error, text
    assert 'dm1  moveable  mm' in text

    is_error, text = _call_tool('get_info',
                                {'section': 'commands', 'name': 'scan'})
    assert not is_error, text
    assert text.splitlines()[2].startswith('scan(')

    is_error, text = _call_tool('get_info',
                                {'section': 'devices', 'name': 'dmm1'})
    assert is_error
    assert 'did you mean' in text


def test_positions_short_form():
    text = mcp_tools.get_device_info(_context())
    assert 'shown 2 of 2 | truncated: no' in text
    assert 'motor1  12.300  deg  ok' in text
    assert 'temp1  4.200  K  busy: ramping' in text
    assert 'hidden' not in text


def test_positions_of_one_setup():
    text = mcp_tools.get_device_info(_context(), setup='base')
    assert 'motor1' in text
    assert 'temp1' not in text
    with pytest.raises(ToolError, match='did you mean: base'):
        mcp_tools.get_device_info(_context(), setup='bsae')


def test_positions_detail():
    text = mcp_tools.get_device_info(_context(), devices=['motor1'])
    assert '# truncated: no' in text
    assert 'value: 12.300 deg' in text
    assert 'status: ok' in text
    assert 'last target: 12.300 deg' in text
    assert 'user limits: -10.000 .. 90.000' in text
    assert 'absolute limits: -180.000 .. 180.000' in text
    assert 's ago)' in text
    # only allowlisted cache keys are ever read
    assert 'secret123' not in text


def test_positions_switch_without_unit():
    context = _context()
    switch = context.session.devices['temp1']
    switch.unit = ''
    switch.valuetype = oneof('open', 'closed')
    context.session.cache.db['temp1/value'] = 'open'
    text = mcp_tools.get_device_info(context, devices=['temp1'])
    assert 'value: open\n' in text
    assert 'allowed values: open, closed' in text
    text = mcp_tools.get_info(context, section='devices', name='temp1')
    assert 'allowed values: open, closed' in text
    switch.valuetype = oneof('', 'other')
    text = mcp_tools.get_device_info(context, devices=['temp1'])
    assert "allowed values: '', other" in text


def test_positions_empty_and_none_values():
    context = _context()
    context.session.cache.db['motor1/value'] = ''
    context.session.cache.db['temp1/value'] = None
    text = mcp_tools.get_device_info(context)
    assert "motor1  ''  deg  ok" in text
    assert 'temp1  none  K  busy: ramping' in text


def test_instructions_name_only_existing_tools():
    names = {tool.name for tool in mcp_tools.TOOLS}
    for text in [INSTRUCTIONS] + mcp_tools.RULES:
        mentioned = set(re.findall(r'\b(?:get|create)_\w+|\bdry_run\b', text))
        assert mentioned <= names, text


class FakeAlias(FakeDevice):
    def __init__(self, alias):
        FakeDevice.__init__(self, '', 'deg')
        self.alias = alias


def test_alias(monkeypatch):
    monkeypatch.setattr(mcp_tools, 'DeviceAlias', FakeAlias)
    context = _context()
    context.session.devices['rot'] = FakeAlias('motor1')
    text = mcp_tools.get_device_info(context, devices=['rot'])
    assert 'description: Sample rotation' in text
    assert 'alias of: motor1' in text
    assert 'test_mcp_tools.FakeDevice' in text
    text = mcp_tools.get_info(context, section='devices')
    assert 'rot  device  deg  alias of motor1' in text


def test_detector_without_value(monkeypatch):
    monkeypatch.setattr(mcp_tools, 'Measurable', FakeDevice)
    text = mcp_tools.get_device_info(_context(), devices=['hidden'])
    assert 'value: ? - no current value; detectors have one only during ' \
        'and shortly after counting' in text


def test_positions_missing_value():
    text = mcp_tools.get_device_info(_context(), devices=['hidden'])
    assert 'value: ? - no value in cache' in text


def test_target_of_moving_device():
    context = _context()
    context.session.cache.db['temp1/target'] = 5.0
    text = mcp_tools.get_device_info(context, devices=['temp1'])
    # temp1 is busy, so this is where it is going
    assert 'target: 5.000 K' in text
    assert 'last target' not in text


def test_devices_as_string():
    assert mcp_tools.get_device_info(_context(), devices='motor1') == \
        mcp_tools.get_device_info(_context(), devices=['motor1'])


def test_setup_not_loaded():
    context = _context()
    context.session.getSetupInfo()['cryo'] = {'description': 'Cryostat'}
    for call in (lambda: mcp_tools.get_device_info(context, setup='cryo'),
                 lambda: mcp_tools.get_info(context, section='setups',
                                            name='Cryo')):
        with pytest.raises(ToolError, match="setup '[Cc]ryo' exists but is "
                                            "not loaded; loaded setups: "
                                            "base, extra"):
            call()
    with pytest.raises(ToolError, match="unknown loaded setup 'nosuch'"):
        mcp_tools.get_device_info(context, setup='nosuch')


def test_setup_devices_sorted_ignoring_case():
    context = _context()
    context.session.devices['Zmotor'] = FakeDevice('Z axis', 'mm')
    context.session.getSetupInfo()['extra']['devices']['Zmotor'] = None
    text = mcp_tools.get_info(context, section='setups', name='extra')
    assert text.index('temp1') < text.index('Zmotor')


def test_index_without_matches():
    text = mcp_tools.get_info(_context(), section='commands', name='zz*')
    assert 'shown 0 of 0' in text
    assert '# nothing found' in text
    text = mcp_tools.get_info(_context(), section='commands')
    assert 'nothing found' not in text


def test_positions_bad_arguments():
    with pytest.raises(ToolError, match='did you mean: motor1'):
        mcp_tools.get_device_info(_context(), devices=['motr1'])
    with pytest.raises(ToolError, match='not both'):
        mcp_tools.get_device_info(_context(), devices=['motor1'],
                                       setup='base')
    with pytest.raises(ToolError, match='at most'):
        mcp_tools.get_device_info(
            _context(), devices=['motor1'] * (mcp_tools.MAX_DETAIL_DEVICES + 1))
    context = _context()
    context.session.cache = None
    with pytest.raises(ToolError, match='no cache connection'):
        mcp_tools.get_device_info(context)


def test_get_device_info_on_daemon(client):
    load_setup(client, 'daemontest')
    client.run_and_wait('read(dm1)')

    is_error, text = _call_tool('get_device_info', {})
    assert not is_error, text
    assert 'dm1  ' in text

    is_error, text = _call_tool('get_device_info', {'devices': ['dm1']})
    assert not is_error, text
    assert 'mm' in text
    assert 'user limits: -50' in text
    assert 'absolute limits: -100' in text

    is_error, text = _call_tool('get_device_info', {'device': 'dm1'})
    assert is_error
    assert text == "unknown argument 'device'; allowed: devices, setup"
