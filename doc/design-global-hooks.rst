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
:ref:`specialized variables <specialized-variables>`, corresponding to
the surrounded opcode, will also be provided. See
:ref:`per-opcode hooks parameters documentation <opcode-params>` for
more details.

For the opcodes that are currently unsupported by hooks, and thus, don't
presented in :ref:`opcodes list <opcode-params>`, only
:ref:`common variables <common-variables>` will be available in the
corresponding *global* hooks. *OBJECT_TYPE* variable for such hooks will
be initialized with special ``NOT_APPLICABLE`` value. The hooks will be
executed only on master daemon as their opcodes won't provide any lists
containing target nodes.

Additional variables
~~~~~~~~~~~~~~~~~~~~

The additional variable is introduced for both pre and post hooks
in order to identify the current job:

GANETI_JOB_ID
  Id of the job current opcode belongs to.

Due to the fact that global hooks will be executed even after job
process has dead, a new environmental variable is introduced for the
*global* post hooks:

GANETI_POST_STATUS
  String containing status of the opcode execution: ``succeeded``,
  ``failed`` or ``disappeared``.

  The ``succeded`` status means that the logical unit corresponding to
  opcode succesfully finished.

  The ``failed`` status means that the corresponding logical unit caused
  an exception which has been logged.

  The ``disappeared`` status means that job process has died during
  the logical unit execution.

Behaviour details
~~~~~~~~~~~~~~~~~

The code executing the logical unit will start a process which will be
responsible for the *global* hooks execution. All the pre hooks will end
their execution before the start of the opcode execution on each node.
All the post hooks will start after the end of logical unit execution or
after the job process death. In case of the job process death, the hooks
will not be executed for the further opcodes in the job.

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
