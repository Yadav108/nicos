.. _install-nicos:

Installing NICOS
================

Get the source code
-------------------

NICOS is maintained in a Git repository hosted at the FRM II.  You can clone
this repository using ::

  git clone https://forge.frm2.tum.de/review/frm2/nicos/nicos

Alternatively you can get the current snapshot from

  http://forge.frm2.tum.de/cgit/cgit.cgi/frm2/nicos/nicos.git/snapshot/nicos-master.tar.bz2

For development, we use SSH access via Gerrit::

  git clone ssh://forge.frm2.tum.de:29418/frm2/nicos/nicos

Note that you have to log in once at the `FRM II Gerrit instance
<http://forge.frm2.tum.de/review/>`_ and add a public key for SSH, since only
public key authentication is enabled.

The bug tracker and project wiki are at

  https://forge.frm2.tum.de/projects/nicos/


.. include:: ../../INSTALL

.. _inst_demo:             

Running the demonstration setup
-------------------------------

After installing NICOS according to the instructions above, you can start the
individual :ref:`components <components>`. A setup that uses all the major
components can be started with the single command::

  uv run nicos-demo

This starts the cache, poller, electronic logbook, and daemon services, and also
starts the graphical interface and a status monitor.

It will load the demo setups from ``nicos_demo/demo/setups``.  The startup setup
contains a few devices that show basic usage of the NICOS system.  Call
``help()`` to get a list of commands.  You can also call ``help(dev)`` to get
help for an individual device.

.. You can continue with :ref:`the first steps <firststeps>` from here.


Configure NICOS
---------------

On startup, the toplevel ``nicos.conf`` file (see :ref:`nicosconf`) will be
searched for in the following locations (in order):

- in the site-wide directory, i.e. ``/etc/xdg/nicos/nicos.conf`` on GNU/Linux, or 
- the ``nicos`` directory in your standard user configuration path, i.e. on
  GNU/Linux systems, this would be ``~/.config/nicos/nicos.conf``.

Both these paths can be modified by setting the ``XDG_CONFIG_DIRS`` or
``XDG_CONFIG_HOME`` environment variable, respectively, to point to a different
location. See the corresponding XDG variable documentation for reference:
https://platformdirs.readthedocs.io/en/latest/parameters.html#xdg-env-vars

For backwards compatibility, the root of the source repository (i.e. the
``nicos_root`` folder) will be searched first. In case NICOS has been deployed from
a wheel package, this path would most likely not point to a suitable location.
Therefore, prefer the XDG standard directories as place for ``nicos.conf``.

   
Build the distribution
------------------------------------

You can build source and wheel packages by running::

  uv build --all-packages

Similarly as with the ``sync`` command, you can specify single packages instead by using e.g.::

  uv build --package nicos-demo

To publish the resulting package(s) to an index, use::

  uv publish

