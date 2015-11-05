==============================================
Better Ganeti customization using global hooks
==============================================

This document describes an enhancement of Ganeti's customisation by
introducing global hooks that will be run before and after each Ganeti
opcode even if the job process has dead.

.. contents:: :depth: 4

Current state and shortcomings
==============================

Currently, Ganeti allows customization of operations by running scripts
in sub-directories of ``@SYSCONFDIR@/ganeti/hooks``. These
sub-directories are named ``$hook-$phase.d``, where ``$phase`` is either
``pre`` or ``post`` and ``$hook`` matches the directory name given for
a hook (e.g. ``cluster-verify-post.d`` or ``node-add-pre.d``). Post
hooks for opcodes don't run in case of the job process has died. The
:doc:`hooks` design document describes currently existing hooks in
more details.

In some situations, e.g., reporting to upper level tools controlling
Ganeti, it is desirable to run hooks before and after each opcode
execution. Users currently work around this problem by creating symbolic
links for each opcode directory. But in that case, a problem of the job
processes death remains. In that case post-opcode hooks wouldn't run
because the opcode execution didn't finish.

Other problem is that some opcodes don't support hooks. That makes it
impossible for external tools to setup hook for each opcode execution
that might be useful, e.g. for monitoring puproses.

Proposed changes
================

We propose to introduce a new type of hooks, the *global* hooks, that
run before and after each opcode execution even in case of opcode
process death. The organization of such hooks will be preserved the
same as for the :ref:`existing per-opcode hooks <hooks-organization>`.
The same :ref:`common variables <common-variables>` will be available as
for the usual hooks. In addition to common variables,
:ref:`additional variables <additional-variables>` and
:ref:`specialized variables <specialized-variables>`, corresponding to
the surrounded opcode, will also be provided. See
:ref:`per-opcode hooks parameters documentation <opcode-params>` for
more details.

For the opcodes that are currently unsupported by hooks, and thus, don't
presented in :ref:`opcodes list <opcode-params>`, only
:ref:`common variables <common-variables>` and
:ref:`additional variables <additional-variables>` will be available
inside the *global* hooks. *OBJECT_TYPE* variable for such hooks will
be initialized with special ``NOT_APPLICABLE`` value. The hooks will be
executed only on master daemon as their opcodes won't provide any lists
containing target nodes.

For the *global* post hooks executing after a failure or death of
the job process, only :ref:`common variables <common-variables>`
(except OBJECT_TYPE) and
:ref:`additional variables <additional-variables>` will be provided.

.. _additional-variables:

Additional variables
~~~~~~~~~~~~~~~~~~~~

The additional variable is introduced for both pre and post hooks
in order to identify the current job:

GANETI_JOB_ID
  Id of the job current opcode belongs to.

GANETI_IS_MASTER
  The variable showing if the current node is a master node. It might
  be useful e.g. if global hooks are used for the logging purposes.

  The ``master`` value means that the node is the master node

  The ``not_master`` value means that the node is not the master

Due to the fact that global hooks will be executed even after job
process has dead, a new environmental variable is introduced for the
*global* post hooks:

GANETI_POST_STATUS
  String containing status of the opcode execution: ``success``,
  ``error`` or ``disappeared``.

  The ``success`` status means that the logical unit corresponding to
  the opcode and the non-global post hooks for the opcodes have
  succesfully finished.

  The ``error`` status means that the corresponding logical unit or
  the non-global hooks caused an exception which has been logged.

  The ``disappeared`` status means that the job process has died during
  the logical unit or the non-global hooks execution.

Behaviour details
~~~~~~~~~~~~~~~~~

*Global* pre hooks will always be executed just before the usual pre
hooks on the same node set and on the master node. The hooks
execution result will be ignored. In case of opcodes which don't
support hooks, *global* pre hooks also will be executed but only on
the master node.

With the post hooks the situation is more complicated. In case of
successful job process execution, *global* hooks will be executed just
after the usual post hooks have run and all the errors have been
checked. In case of ``error`` status, *global* post hooks will be
executed only on the master node from the exception handler. Just after
the *global* post hooks execution, the exception will be raised again
as usual. In case of job process disappear, the scheduler will execute
the *global* post hooks in a separate process as soon as the job
process death is registered. The *global* post hooks will be executed
only for the opcodes with an initialized start_timestamp.

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
