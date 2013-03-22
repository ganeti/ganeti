===================
Ganeti reason trail
===================

.. contents:: :depth: 2

This is a design document detailing the implementation of a way for Ganeti to
track the origin and the reason of every executed command, from its starting
point (command line, remote API, some htool, etc.) to its actual execution
time.

Current state and shortcomings
==============================

There is currently no way to track why a job and all the operations part of it
were executed, and who or what triggered the execution.
This is an inconvenience in general, and also it makes impossible to have
certain information, such as finding the reason why an instance last changed its
status (i.e.: why it was started/stopped/rebooted/etc.), or distinguishing
an admin request from a scheduled maintenance or an automated tool's work.

Proposed changes
================

We propose to introduce a new piece of information, that will be called "reason
trail", to track the path from the issuing of a command to its execution.

The reason trail will be a list of 3-tuples ``(source, reason, timestamp)``,
with:

``source``
  The entity deciding to perform (or forward) a command.
  It is represented by an arbitrary string, but strings prepended by "gnt:"
  are reserved for Ganeti components, and they will be refused by the
  interfaces towards the external world.

``reason``
  The reason why the entity decided to perform the operation.
  It is represented by an arbitrary string. The string might possibly be empty,
  because certain components of the system might just "pass on" the operation
  (therefore wanting to be recorded in the trail) but without an explicit
  reason.

``timestamp``
  The time when the element was added to the reason trail. It has to be
  expressed in nanoseconds since the unix epoch (0:00:00 January 01, 1970).
  If not enough precision is available (or needed) it can be padded with
  zeroes.

The reason trail will be attached at the OpCode level. When it has to be
serialized externally (such as on the RAPI interface), it will be serialized in
JSON format. Specifically, it will be serialized as a list of elements.
Each element will be a list with two strings (for ``source`` and ``reason``)
and one integer number (the ``timestamp``).

Any component the operation goes through is allowed (but not required) to append
it's own reason to the list. Other than this, the list shouldn't be modified.

As an example here is the reason trail for a shutdown operation invoked from
the command line through the gnt-instance tool::

  [("user", "Cleanup of unused instances", 1363088484000000000),
   ("gnt:client:gnt-instance", "stop", 1363088484020000000),
   ("gnt:opcode:shutdown", "job=1234;index=0", 1363088484026000000),
   ("gnt:daemon:noded:shutdown", "", 1363088484135000000)]

where the first 3-tuple is determined by a user-specified message, passed to
gnt-instance through a command line parameter.

The same operation, launched by an external GUI tool, and executed through the
remote API, would have a reason trail like::

  [("user", "Cleanup of unused instances", 1363088484000000000),
   ("other-app:tool-name", "gui:stop", 1363088484000300000),
   ("gnt:client:rapi:shutdown", "", 1363088484020000000),
   ("gnt:library:rlib2:shutdown", "", 1363088484023000000),
   ("gnt:opcode:shutdown", "job=1234;index=0", 1363088484026000000),
   ("gnt:daemon:noded:shutdown", "", 1363088484135000000)]

Implementation
==============

The OpCode base class will be modified to include a new parameter, "reason".
This will receive the reason trail as built by all the previous steps.

When an OpCode is added to a job (in jqueue.py) the job number and the opcode
index will be recorded as the reason for the existence of that opcode.

From the command line tools down to the opcodes, the implementation of this
design will be shared by all the components of the system. After the opcodes
have been enqueued in a job queue and are dispatched for execution, the
implementation will have to be OpCode specific because of the current
structure of the ganeti backend.

The implementation of opcode-specific parts will start from the operations that
affect the instance status (as required by the design document about the
monitoring daemon, for the instance status data collector). Such opcodes will
be changed so that the "reason" is passed to them and they will then export
the reason trail on a file.

The implementation for other opcodes will follow when required.

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
