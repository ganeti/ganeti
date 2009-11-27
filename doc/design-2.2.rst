=================
Ganeti 2.2 design
=================

This document describes the major changes in Ganeti 2.2 compared to
the 2.1 version.

The 2.2 version will be a relatively small release. Its main aim is to
avoid changing too much of the core code, while addressing issues and
adding new features and improvements over 2.1, in a timely fashion.

.. contents:: :depth: 4

Objective
=========

Background
==========

Overview
========

Detailed design
===============

As for 2.1 we divide the 2.2 design into three areas:

- core changes, which affect the master daemon/job queue/locking or
  all/most logical units
- logical unit/feature changes
- external interface changes (eg. command line, os api, hooks, ...)

Core changes
------------

Remote procedure call timeouts
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Current state and shortcomings
++++++++++++++++++++++++++++++

The current RPC protocol used by Ganeti is based on HTTP. Every request
consists of an HTTP PUT request (e.g. ``PUT /hooks_runner HTTP/1.0``)
and doesn't return until the function called has returned. Parameters
and return values are encoded using JSON.

On the server side, ``ganeti-noded`` handles every incoming connection
in a separate process by forking just after accepting the connection.
This process exits after sending the response.

There is one major problem with this design: Timeouts can not be used on
a per-request basis. Neither client or server know how long it will
take. Even if we might be able to group requests into different
categories (e.g. fast and slow), this is not reliable.

If a node has an issue or the network connection fails while a request
is being handled, the master daemon can wait for a long time for the
connection to time out (e.g. due to the operating system's underlying
TCP keep-alive packets or timeouts). While the settings for keep-alive
packets can be changed using Linux-specific socket options, we prefer to
use application-level timeouts because these cover both machine down and
unresponsive node daemon cases.

Proposed changes
++++++++++++++++

RPC glossary
^^^^^^^^^^^^

Function call ID
  Unique identifier returned by ``ganeti-noded`` after invoking a
  function.
Function process
  Process started by ``ganeti-noded`` to call actual (backend) function.

Protocol
^^^^^^^^

Initially we chose HTTP as our RPC protocol because there were existing
libraries, which, unfortunately, turned out to miss important features
(such as SSL certificate authentication) and we had to write our own.

This proposal can easily be implemented using HTTP, though it would
likely be more efficient and less complicated to use the LUXI protocol
already used to communicate between client tools and the Ganeti master
daemon. Switching to another protocol can occur at a later point. This
proposal should be implemented using HTTP as its underlying protocol.

The LUXI protocol currently contains two functions, ``WaitForJobChange``
and ``AutoArchiveJobs``, which can take a longer time. They both support
a parameter to specify the timeout. This timeout is usually chosen as
roughly half of the socket timeout, guaranteeing a response before the
socket times out. After the specified amount of time,
``AutoArchiveJobs`` returns and reports the number of archived jobs.
``WaitForJobChange`` returns and reports a timeout. In both cases, the
functions can be called again.

A similar model can be used for the inter-node RPC protocol. In some
sense, the node daemon will implement a light variant of *"node daemon
jobs"*. When the function call is sent, it specifies an initial timeout.
If the function didn't finish within this timeout, a response is sent
with a unique identifier, the function call ID. The client can then
choose to wait for the function to finish again with a timeout.
Inter-node RPC calls would no longer be blocking indefinitely and there
would be an implicit ping-mechanism.

Request handling
^^^^^^^^^^^^^^^^

To support the protocol changes described above, the way the node daemon
handles request will have to change. Instead of forking and handling
every connection in a separate process, there should be one child
process per function call and the master process will handle the
communication with clients and the function processes using asynchronous
I/O.

Function processes communicate with the parent process via stdio and
possibly their exit status. Every function process has a unique
identifier, though it shouldn't be the process ID only (PIDs can be
recycled and are prone to race conditions for this use case). The
proposed format is ``${ppid}:${cpid}:${time}:${random}``, where ``ppid``
is the ``ganeti-noded`` PID, ``cpid`` the child's PID, ``time`` the
current Unix timestamp with decimal places and ``random`` at least 16
random bits.

The following operations will be supported:

``StartFunction(fn_name, fn_args, timeout)``
  Starts a function specified by ``fn_name`` with arguments in
  ``fn_args`` and waits up to ``timeout`` seconds for the function
  to finish. Fire-and-forget calls can be made by specifying a timeout
  of 0 seconds (e.g. for powercycling the node). Returns three values:
  function call ID (if not finished), whether function finished (or
  timeout) and the function's return value.
``WaitForFunction(fnc_id, timeout)``
  Waits up to ``timeout`` seconds for function call to finish. Return
  value same as ``StartFunction``.

In the future, ``StartFunction`` could support an additional parameter
to specify after how long the function process should be aborted.

Simplified timing diagram::

  Master daemon        Node daemon                      Function process
   |
  Call function
  (timeout 10s) -----> Parse request and fork for ----> Start function
                       calling actual function, then     |
                       wait up to 10s for function to    |
                       finish                            |
                        |                                |
                       ...                              ...
                        |                                |
  Examine return <----  |                                |
  value and wait                                         |
  again -------------> Wait another 10s for function     |
                        |                                |
                       ...                              ...
                        |                                |
  Examine return <----  |                                |
  value and wait                                         |
  again -------------> Wait another 10s for function     |
                        |                                |
                       ...                              ...
                        |                                |
                        |                               Function ends,
                       Get return value and forward <-- process exits
  Process return <---- it to caller
  value and continue
   |

.. TODO: Convert diagram above to graphviz/dot graphic

On process termination (e.g. after having been sent a ``SIGTERM`` or
``SIGINT`` signal), ``ganeti-noded`` should send ``SIGTERM`` to all
function processes and wait for all of them to terminate.


Feature changes
---------------

External interface changes
--------------------------

.. vim: set textwidth=72 :
