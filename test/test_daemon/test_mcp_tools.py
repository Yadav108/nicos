"""Tests for the daemon's MCP tools."""

import json
import logging
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
from nicos.utils.loggers import INPUT

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


def _context(status=STATUS_IDLE, script=None, messages=()):
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
    return McpContext(session, SimpleNamespace(_controller=controller,
                                               _messages=list(messages)))


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


# -- output logs, with messages shaped like those of a real daemon ---------

T0 = time.mktime((2026, 11, 24, 14, 44, 0, 0, 0, -1))
NAME_ERROR = '''\
Traceback (most recent call last):
  File "/nicos/services/daemon/script.py", line 157, in execute
    controller.start_exec(self.code[self.curblock],
        password             = 'hunter2'

  File "<script>", line 3, in <module>
    x = undefined_name
NameError: name 'undefined_name' is not defined'''
LIMIT_ERROR = '''\
Traceback (most recent call last):
  File "/nicos/core/device.py", line 1707, in _check_start
    raise LimitError(self, 'moving to %s is not allowed: %s' %
        pos                  = 9999.0

nicos.core.errors.LimitError: [sth_st] moving to 9999.000 deg is not allowed'''
MESSAGES = [
    ('nicos', T0, INPUT,
     '>>> [admin 2026-11-24 14:44:00]  scan(sth, 304, 0.5, 5, t=0.2)\n',
     None, 'r1'),
    ('nicos', T0 + 1, logging.INFO, '=' * 100 + '\n', None, 'r1'),
    ('nicos', T0 + 2, logging.INFO,
     '1/5      304.000  2.001    0.200    637\n', None, 'r1'),
    ('nicos', T0 + 3, logging.DEBUG, 'debug detail\n', None, 'r1'),
    ('nicos', T0 + 60, INPUT,
     '>>> [user 2026-11-24 14:45:00] -------------------- run.py\n'
     'for i in range(2):\n    maw(T, 5)\nx = undefined_name\n' + '-' * 40,
     None, 'r2'),
    ('T', T0 + 61, logging.INFO, 'moving to 5.000 K\n', None, 'r2'),
    ('nicos', T0 + 62, logging.WARNING, 'helium level low\n', None, 'r2'),
    ('nicos', T0 + 63, logging.ERROR,
     "NameError - name 'undefined_name' is not defined\n", NAME_ERROR, 'r2'),
    ('sth_st', T0 + 64, logging.ERROR, 'Out of bounds - [sth_st] moving to '
     '9999.000 deg is not allowed\n', LIMIT_ERROR, 'r3'),
]


def _logs(messages=None, **arguments):
    context = _context(messages=MESSAGES if messages is None else messages)
    return mcp_tools.get_output_logs(context, **arguments)


def test_logs_all():
    text = _logs()
    lines = text.splitlines()
    assert lines[0].startswith('# get_output_logs | view=all | '
                               '14:44:00 to 14:45:04 (')
    assert lines[1] == '# shown 8 of 8 | truncated: no | cursor: none'
    assert '# buffer: 9 messages since 2026-11-24 14:44:00' in text
    assert '14:44:00 > scan(sth, 304, 0.5, 5, t=0.2) (by admin)' in lines
    # rulers and blank runs that only align console output are shortened
    assert '14:44:01 ==========' in lines
    assert '14:44:02 1/5  304.000  2.001  0.200  637' in lines
    assert 'debug detail' not in text
    assert '14:45:01 T: moving to 5.000 K' in lines
    assert '14:45:02 WARNING helium level low' in lines


def test_logs_tracebacks_are_short():
    lines = _logs().splitlines()
    i = lines.index("14:45:03 ERROR NameError - name 'undefined_name' is "
                    "not defined")
    assert lines[i + 1] == '    stopped at script line 3: x = undefined_name'
    assert lines[i + 2].startswith('14:45:04 ERROR sth_st: Out of bounds')
    text = '\n'.join(lines)
    # no frames, no local variables
    assert 'hunter2' not in text
    assert 'device.py' not in text


def test_logs_traceback_keeps_new_exception_text():
    message = ('nicos', T0, logging.ERROR, 'error in scan\n',
               'Traceback (most recent call last):\n  File "x.py", line 1\n'
               'ValueError: bad step', None)
    assert '    ValueError: bad step' in _logs([message]).splitlines()


def test_logs_script_code_keeps_indentation():
    lines = _logs(view='input').splitlines()
    i = lines.index('14:45:00 > script run.py (by user):')
    assert lines[i + 1:i + 4] == ['    for i in range(2):',
                                  '        maw(T, 5)',
                                  '    x = undefined_name']
    assert not any(set(line.strip()) == {'-'} for line in lines)


def test_logs_views():
    text = _logs(view='input')
    assert 'shown 2 of 2' in text
    assert 'moving to' not in text
    text = _logs(view='problems')
    assert 'shown 5 of 5' in text
    assert 'helium level low' in text
    assert 'run.py' in text
    assert 'moving to 5.000 K' not in text


def test_logs_paging_with_cursor():
    text = _logs(last_n=3)
    assert '# shown 3 of 8 | truncated: yes | cursor: %r' % (T0 + 62) in text
    assert 'cursor=' in text
    text = _logs(last_n=3, cursor=repr(T0 + 62))
    assert 'shown 3 of 5 | truncated: yes' in text
    assert '14:44:02 1/5' in text
    assert 'helium' not in text
    text = _logs(last_n=3, cursor=repr(T0 + 2))
    assert 'shown 2 of 2 | truncated: no | cursor: none' in text


def test_logs_time_window():
    assert 'shown 5 of 5' in _logs(**{'from': '2026-11-24 14:45'})
    assert 'shown 3 of 3' in _logs(**{'to': '2026-11-24T14:44:30'})
    now = time.time()
    recent = [('nicos', now - 7200, logging.INFO, 'two hours ago', None, ''),
              ('nicos', now - 60, logging.INFO, 'a minute ago', None, '')]
    text = _logs(recent, **{'from': '-1h', 'to': 'now'})
    assert 'a minute ago' in text
    assert 'two hours ago' not in text
    assert 'shown 2 of 2' in _logs(recent, **{'from': '-3h'})


def test_logs_filter():
    assert 'shown 1 of 1' in _logs(filter='HELIUM')
    # also matches the source of a message
    assert '14:45:01 T: moving' in _logs(filter='^T$')
    # not a valid regular expression: used as plain text
    text = _logs(filter='scan(')
    assert 'shown 1 of 1' in text
    assert "filter='scan('" in text
    text = _logs(filter='nothing like this')
    assert '# nothing found' in text


def test_logs_dates_across_days():
    messages = [('nicos', T0 - 86400, logging.INFO, 'yesterday', None, ''),
                ('nicos', T0, logging.INFO, 'today', None, '')]
    assert '2026-11-24 14:44:00 today' in _logs(messages).splitlines()


def test_logs_size_limits():
    messages = [('nicos', T0 + i, logging.INFO, 'x' * 5000, None, '')
                for i in range(mcp_tools.MAX_LOG_ITEMS)]
    text = _logs(messages, last_n=mcp_tools.MAX_LOG_ITEMS)
    assert len(text) <= mcp_tools.REPLY_LIMIT
    assert '[cut, 4700 more chars]' in text
    assert 'truncated: yes' in text
    # the newest messages are kept
    assert _logs(messages[-1:]).splitlines()[-1] in text.splitlines()
    script = ('nicos', T0, INPUT, '>>> [a 2026-11-24 14:44:00] -- x\n' +
              'read()\n' * 1000, None, '')
    assert '[cut, ' in _logs([script])


def test_logs_empty_buffer():
    text = _logs([])
    assert '# nothing found' in text
    assert 'buffer: empty' in text
    assert 'logs: none yet' in mcp_tools.get_overview(_context())
    assert 'logs: 9 messages since 2026-11-24 14:44:00 -> get_output_logs' \
        in mcp_tools.get_overview(_context(messages=MESSAGES))


@pytest.mark.parametrize('arguments, error', [
    ({'view': 'inputs'}, 'did you mean: input'),
    ({'last_n': 0}, 'last_n must be'),
    ({'last_n': 201}, 'last_n must be'),
    ({'last_n': '5'}, 'last_n must be'),
    ({'last_n': True}, 'last_n must be'),
    ({'from': 'yesterday'}, "cannot read from='yesterday'"),
    ({'cursor': 'abc'}, 'invalid cursor'),
])
def test_logs_bad_arguments(arguments, error):
    with pytest.raises(ToolError, match=error):
        _logs(**arguments)


def test_get_output_logs_on_daemon(client):
    load_setup(client, 'daemontest')
    client.run_and_wait("printinfo('hello from the mcp test')")

    is_error, text = _call_tool('get_output_logs', {'filter': 'mcp test'})
    assert not is_error, text
    assert re.search(r"\d\d:\d\d:\d\d > printinfo\('hello from the mcp "
                     r"test'\) \(by user\)", text)
    assert re.search(r'\d\d:\d\d:\d\d hello from the mcp test', text)

    is_error, text = _call_tool('get_output_logs', {'view': 'input',
                                                    'last_n': 1})
    assert not is_error, text
    assert 'shown 1 of' in text
