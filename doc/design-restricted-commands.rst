Design for executing commands via RPC
=====================================

.. contents:: :depth: 3


Current state and shortcomings
------------------------------

We have encountered situations where a node was no longer responding to
attempts at connecting via SSH or SSH became unavailable through other
means. Quite often the node daemon is still available, even in
situations where there's little free memory. The latter is due to the
node daemon being locked into main memory using ``mlock(2)``.

Since the node daemon does not allow the execution of arbitrary
commands, quite often the only solution left was either to attempt a
powercycle request via said node daemon or to physically reset the node.


Proposed changes
----------------

The goal of this design is to allow the execution of non-arbitrary
commands via RPC requests. Since this can be dangerous in case the
cluster certificate (``server.pem``) is leaked, some precautions need to
be taken:

- No parameters may be passed
- No absolute or relative path may be passed, only a filename
- Executable must reside in ``/etc/ganeti/restricted-commands``, which must
  be owned by root:root and have mode 0755 or stricter
  - Must be regular files or symlinks
  - Must be executable by root:root

There shall be no way to list available commands or to retrieve an
executable's contents. The result from a request to execute a specific
command will either be its output and exit code, or a generic error
message. Only the receiving node's log files shall contain information
as to why executing the command failed.

To slow down dictionary attacks on command names in case an attacker
manages to obtain a copy of ``server.pem``, a system-wide, file-based
lock is acquired before verifying the command name and its executable.
If a command can not be executed for some reason, the lock is only
released with a delay of several seconds, after which the generic error
message will be returned to the caller.

At first, restricted commands will not be made available through the
:doc:`remote API <rapi>`, though that could be done at a later point
(with a separate password).

On the command line, a new sub-command will be added to the ``gnt-node``
script.

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
