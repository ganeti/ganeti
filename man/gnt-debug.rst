gnt-debug(8) Ganeti | Version @GANETI_VERSION@
==============================================

Name
----

gnt-debug - Debug commands

Synopsis
--------

**gnt-debug** {command} [arguments...]

DESCRIPTION
-----------

The **gnt-debug** is used for debugging the Ganeti system.

COMMANDS
--------

IALLOCATOR
~~~~~~~~~~

**iallocator** [\--debug] [\--dir *DIRECTION*] {\--algorithm
*ALLOCATOR* } [\--mode *MODE*] [\--mem *MEMORY*] [\--disks *DISKS*]
[\--disk-template *TEMPLATE*] [\--nics *NICS*] [\--os-type *OS*]
[\--vcpus *VCPUS*] [\--tags *TAGS*] {*instance*}

Executes a test run of the *iallocator* framework.

The command will build input for a given iallocator script (named
with the ``--algorithm`` option), and either show this input data
(if *DIRECTION* is ``in``) or run the iallocator script and show its
output (if *DIRECTION* is ``out``).

If the *MODE* is ``allocate``, then an instance definition is built
from the other arguments and sent to the script, otherwise (*MODE* is
``relocate``) an existing instance name must be passed as the first
argument.

This build of Ganeti will look for iallocator scripts in the following
directories: @CUSTOM_IALLOCATOR_SEARCH_PATH@; for more details about
this framework, see the HTML or PDF documentation.

DELAY
~~~~~

**delay** [\--debug] [\--no-master] [\--interruptible] [-n *NODE*...]
{*duration*}

Run a test opcode (a sleep) on the master and on selected nodes
(via an RPC call). This serves no other purpose but to execute a
test operation.

The ``-n`` option can be given multiple times to select the nodes
for the RPC call. By default, the delay will also be executed on
the master, unless the ``--no-master`` option is passed.

The ``--interruptible`` option allows a running delay opcode to be
interrupted by communicating with a special domain socket. If any data
is sent to the socket, the delay opcode terminates. If this option is
used, no RPCs are performed, but locks are still acquired.

The *delay* argument will be interpreted as a floating point
number.

SUBMIT-JOB
~~~~~~~~~~

**submit-job** [\--verbose] [\--timing-stats] [\--job-repeat *N*]
[\--op-repeat *N*] [\--each] {opcodes_file...}

This command builds a list of opcodes from files in JSON format and
submits a job per file to the master daemon. It can be used to test
options that are not available via command line.

The ``verbose`` option will additionally display the corresponding
job IDs and the progress in waiting for the jobs; the
``timing-stats`` option will show some overall statistics inluding
the number of total opcodes, jobs submitted and time spent in each
stage (submit, exec, total).

The ``job-repeat`` and ``op-repeat`` options allow to submit
multiple copies of the passed arguments; job-repeat will cause N
copies of each job (input file) to be submitted (equivalent to
passing the arguments N times) while op-repeat will cause N copies
of each of the opcodes in the file to be executed (equivalent to
each file containing N copies of the opcodes).

The ``each`` option allow to submit each job separately (using ``N``
SubmitJob LUXI requests instead of one SubmitManyJobs request).

TEST-JOBQUEUE
~~~~~~~~~~~~~

**test-jobqueue**

Executes a few tests on the job queue. This command might generate
failed jobs deliberately.

TEST_OSPARAMS
~~~~~~~~~~~~~

**test-osparams** {--os-parameters-secret *param*=*value*... }

Tests secret os parameter transmission.

LOCKS
~~~~~

| **locks** [\--no-headers] [\--separator=*SEPARATOR*] [-v]
| [-o *[+]FIELD,...*] [\--interval=*SECONDS*]

Shows a list of locks in the master daemon.

The ``--no-headers`` option will skip the initial header line. The
``--separator`` option takes an argument which denotes what will be
used between the output fields. Both these options are to help
scripting.

The ``-v`` option activates verbose mode, which changes the display of
special field states (see **ganeti**\(7)).

The ``-o`` option takes a comma-separated list of output fields.
The available fields and their meaning are:

@QUERY_FIELDS_LOCK@

If the value of the option starts with the character ``+``, the new
fields will be added to the default list. This allows one to quickly
see the default list plus a few other fields, instead of retyping
the entire list of fields.

Use ``--interval`` to repeat the listing. A delay specified by the
option value in seconds is inserted.

METAD
~~~~~

| **metad** echo *text*

Tests the WConf daemon by invoking its ``echo`` function.

A given text is sent to Metad through RPC, echoed back by Metad and
printed to the console.

WCONFD
~~~~~~

| **wconfd** echo *text*

Tests the WConf daemon by invoking its ``echo`` function.

A given text is sent to WConfd through RPC, echoed back by WConfd and
printed to the console.

| **wconfd** cleanuplocks

A request to clean up all stale locks is sent to WConfd.

| **wconfd** listlocks *jid*

A request to list the locks owned by the given job id is
sent to WConfd and the answer is displayed.

| **wconfd** listalllocks

A request to list all locks in use, directly or indirectly, is
sent to WConfd and the answer is displayed.

| **wconfd** listalllocks

A request to list all locks in use, directly or indirectly, together
with their respective direct owners is sent to WConfd and the answer
is displayed.

| **wconfd** flushconfig

A request to ensure that the configuration is fully distributed to the
master candidates.

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
