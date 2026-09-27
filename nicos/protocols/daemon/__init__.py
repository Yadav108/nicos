# *****************************************************************************
# NICOS, the Networked Instrument Control System of the MLZ
# Copyright (c) 2009-present by the NICOS contributors (see AUTHORS)
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2 of the License, or (at your option) any later
# version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# this program; if not, write to the Free Software Foundation, Inc.,
# 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
#
# Module authors:
#   Georg Brandl <g.brandl@fz-juelich.de>
#
# *****************************************************************************

"""NICOS daemon protocol parts common to server and client."""

# pyctl status constants

STATUS_IDLEEXC  = -2  # nothing started, last script raised exception
STATUS_IDLE     = -1  # nothing started
STATUS_RUNNING  = 0   # execution running
STATUS_INBREAK  = 1   # execution halted, in break function
STATUS_STOPPING = 2   # stop exception raised, waiting for propagation

# break/stop level constants

BREAK_AFTER_LINE = 1  # break after current command in script
BREAK_AFTER_STEP = 2  # break after scan step (or any breakpoint with level 2)
BREAK_NOW = 3         # break "now" (i.e. also while counting)
BREAK_IMMEDIATE = 5   # immediate stop

# daemon command specification

# tuples of
# - command name
# - command code (integer < 65535, will be converted to 2 bytes)
#   (not used in all protocols)

DAEMON_COMMANDS = {
    # script control commands
    'start':          0x01,
    'simulate':       0x02,
    'queue':          0x03,
    'unqueue':        0x04,
    'update':         0x05,
    # script flow commands
    'break':          0x11,
    'continue':       0x12,
    'stop':           0x13,
    'emergency':      0x14,
    'finish':         0x15,
    # async execution commands
    'exec':           0x21,
    'eval':           0x22,
    # watch variable commands
    'watch':          0x31,
    'unwatch':        0x32,
    # enquiries
    'getversion':     0x41,
    'getstatus':      0x42,
    'getmessages':    0x43,
    'getscript':      0x44,
    'gethistory':     0x45,
    'getcachekeys':   0x46,
    'gettrace':       0x47,
    'getdataset':     0x48,
    # miscellaneous commands
    'complete':       0x51,
    'transfer':       0x52,
    'debug':          0x53,
    'debuginput':     0x54,
    # connection related commands
    'eventmask':      0x61,
    'unlock':         0x62,
    'quit':           0x63,
    'authenticate':   0x64,  # only used during handshake
    'eventunmask':    0x65,
    'rearrange':      0x66,
    'keepalive':      0x67,
}

ACTIVE_COMMANDS = {
    'start', 'queue', 'unqueue', 'rearrange', 'update',
    'break', 'continue', 'stop', 'finish', 'exec',  # 'emergency' is allowed
}

# daemon event specification

# key: event name
# value: - event code (integer < 65535, will be converted to 2 bytes)
#        - whether the event data can contain blobs

# IMPORTANT: add new events to the documentation too!

DAEMON_EVENTS = {
    # a new message arrived
    'message':     (0x1001, False),
    # a new request arrived
    'request':     (0x1002, False),
    # a request is now being processed
    'processing':  (0x1003, False),
    # one or more requests have been blocked from execution
    'blocked':     (0x1004, False),
    # the execution status changed
    'status':      (0x1005, False),
    # the watched variables changed
    'watch':       (0x1006, False),
    # the mode changed
    'mode':        (0x1007, False),
    # a new cache value has arrived
    'cache':       (0x1008, False),
    # a new dataset was created
    'dataset':     (0x1009, False),
    # a new point was added to a dataset
    'datapoint':   (0x100A, False),
    # a new fit curve was added to a dataset
    'datacurve':   (0x100B, False),
    # new live data, parameters and blob(s)
    'livedata':    (0x100D, True),
    # a simulation finished with the given result
    'simresult':   (0x100E, False),
    # request to display given help page
    'showhelp':    (0x100F, False),
    # request to execute something on the client side
    'clientexec':  (0x1010, False),
    # a watchdog notification has arrived
    'watchdog':    (0x1011, False),
    # the remote-debugging status changed
    'debugging':   (0x1012, False),
    # a plug-and-play/sample-environment event occurred
    'plugplay':    (0x1013, False),
    # a setup was loaded or unloaded
    'setup':       (0x1014, False),
    # a device was created or destroyed
    'device':      (0x1015, False),
    # the experiment has changed
    'experiment':  (0x1016, False),
    # the user is prompted to continue
    'prompt':      (0x1017, False),
    # queued script has been updated
    'updated':     (0x1018, False),
    # order of queued scripts changed
    'rearranged':  (0x1019, False),
    # estimated finishing time for the currently running script
    'eta':         (0x101A, False),
    # message sent out while simulating
    'simmessage':  (0x101B, False),
    # a request/script is done processing
    'done':        (0x101C, False),
    # a prompt has been answered
    'promptdone':  (0x101D, False),
}

# possible states of ETA simulation

SIM_STATES = {
    'pending': 0x01,
    'running': 0x02,
    'success': 0x03,
    'failed':  0x04,
}


class ProtocolError(Exception):
    """Exception to be raised on protocol/serialization errors."""


class CloseConnection(Exception):
    """Exception to be raised to close the connection gracefully."""
