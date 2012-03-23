ganeti(7) Ganeti | Version @GANETI_VERSION@
===========================================

Name
----

ganeti - cluster-based virtualization management

Synopsis
--------

::

    # gnt-cluster init cluster1.example.com
    # gnt-node add node2.example.com
    # gnt-instance add -n node2.example.com \
    > -o debootstrap --disk 0:size=30g \
    > -t plain instance1.example.com


DESCRIPTION
-----------

The Ganeti software manages physical nodes and virtual instances of a
cluster based on a virtualization software. The current version (2.3)
supports Xen 3.x and KVM (72 or above) as hypervisors, and LXC as an
experimental hypervisor.

Quick start
-----------

First you must install the software on all the cluster nodes, either
from sources or (if available) from a package. The next step is to
create the initial cluster configuration, using **gnt-cluster init**.

Then you can add other nodes, or start creating instances.

Cluster architecture
--------------------

In Ganeti 2.0, the architecture of the cluster is a little more
complicated than in 1.2. The cluster is coordinated by a master daemon
(**ganeti-masterd**(8)), running on the master node. Each node runs
(as before) a node daemon, and the master has the RAPI daemon running
too.

Node roles
~~~~~~~~~~

Each node can be in one of the following states:

master
    Only one node per cluster can be in this role, and this node is the
    one holding the authoritative copy of the cluster configuration and
    the one that can actually execute commands on the cluster and
    modify the cluster state. See more details under
    *Cluster configuration*.

master_candidate
    The node receives the full cluster configuration (configuration
    file and jobs) and can become a master via the
    **gnt-cluster master-failover** command. Nodes that are not in this
    state cannot transition into the master role due to missing state.

regular
    This the normal state of a node.

drained
    Nodes in this state are functioning normally but cannot receive
    new instances, because the intention is to set them to *offline*
    or remove them from the cluster.

offline
    These nodes are still recorded in the Ganeti configuration, but
    except for the master daemon startup voting procedure, they are not
    actually contacted by the master. This state was added in order to
    allow broken machines (that are being repaired) to remain in the
    cluster but without creating problems.


Node flags
~~~~~~~~~~

Nodes have two flags which govern which roles they can take:

master_capable
    The node can become a master candidate, and furthermore the master
    node. When this flag is disabled, the node cannot become a
    candidate; this can be useful for special networking cases, or less
    reliable hardware.

vm_capable
    The node can host instances. When enabled (the default state), the
    node will participate in instance allocation, capacity calculation,
    etc. When disabled, the node will be skipped in many cluster checks
    and operations.


Node Parameters
~~~~~~~~~~~~~~~

The ``ndparams`` refer to node parameters. These can be set as defaults
on cluster and node group levels, but they take effect for nodes only.

Currently we support the following node parameters:

oob_program
    Path to an executable used as the out-of-band helper as described in
    the `Ganeti Node OOB Management Framework <design-oob.rst>`_ design
    document.

spindle_count
    This should reflect the I/O performance of local attached storage
    (e.g. for "file", "plain" and "drbd" disk templates). It doesn't
    have to match the actual spindle count of (any eventual) mechanical
    hard-drives, its meaning is site-local and just the relative values
    matter.


Hypervisor State Parameters
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Using ``--hypervisor-state`` you can set hypervisor specific states as
pointed out in ``Ganeti Resource Model <design-resource-model.rst>``.

The format is: ``hypervisor:option=value``.

Currently we support the following hypervisor state values:

mem_total
  Total node memory, as discovered by this hypervisor
mem_node
  Memory used by, or reserved for, the node itself; note that some
  hypervisors can report this in an authoritative way, other not
mem_hv
  Memory used either by the hypervisor itself or lost due to instance
  allocation rounding; usually this cannot be precisely computed, but
  only roughly estimated
cpu_total
  Total node cpu (core) count; usually this can be discovered
  automatically
cpu_node
  Number of cores reserved for the node itself; this can either be
  discovered or set manually. Only used for estimating how many VCPUs
  are left for instances


Disk State Parameters
~~~~~~~~~~~~~~~~~~~~~

Using ``--disk-state`` you can set disk specific states as pointed out
in ``Ganeti Resource Model <design-resource-model.rst>``.

The format is: ``storage_type/identifier:option=value``. Where we
currently just support ``lvm`` as storage type. The identifier in this
case is the LVM volume group. By default this is ``xenvg``.

Currently we support the following hypervisor state values:

disk_total
  Total disk size (usually discovered automatically)
disk_reserved
  Reserved disk size; this is a lower limit on the free space, if such a
  limit is desired
disk_overhead
  Disk that is expected to be used by other volumes (set via
  ``reserved_lvs``); usually should be zero


Cluster configuration
~~~~~~~~~~~~~~~~~~~~~

The master node keeps and is responsible for the cluster
configuration. On the filesystem, this is stored under the
``@LOCALSTATEDIR@/ganeti/lib`` directory, and if the master daemon is
stopped it can be backed up normally.

The master daemon will replicate the configuration database called
``config.data`` and the job files to all the nodes in the master
candidate role. It will also distribute a copy of some configuration
values via the *ssconf* files, which are stored in the same directory
and start with a ``ssconf_`` prefix, to all nodes.

Jobs
~~~~

All cluster modification are done via jobs. A job consists of one
or more opcodes, and the list of opcodes is processed serially. If
an opcode fails, the entire job is failed and later opcodes are no
longer processed. A job can be in one of the following states:

queued
    The job has been submitted but not yet processed by the master
    daemon.

waiting
    The job is waiting for for locks before the first of its opcodes.

canceling
    The job is waiting for locks, but is has been marked for
    cancellation. It will not transition to *running*, but to
    *canceled*.

running
    The job is currently being executed.

canceled
    The job has been canceled before starting execution.

success
    The job has finished successfully.

error
    The job has failed during runtime, or the master daemon has been
    stopped during the job execution.


Common command line features
----------------------------

Options
~~~~~~~

Many Ganeti commands provide the following options. The
availability for a certain command can be checked by calling the
command using the ``--help`` option.

**gnt-...** *command* [\--dry-run] [\--priority {low | normal | high}]

The ``--dry-run`` option can be used to check whether an operation
would succeed.

The option ``--priority`` sets the priority for opcodes submitted
by the command.

Defaults
~~~~~~~~

For certain commands you can use environment variables to provide
default command line arguments. Just assign the arguments as a string to
the corresponding environment variable. The format of that variable
name is **binary**_*command*. **binary** is the name of the ``gnt-*``
script all upper case and dashes replaced by underscores, and *command*
is the command invoked on that script.

Currently supported commands are ``gnt-node list``, ``gnt-group list``
and ``gnt-instance list``. So you can configure default command line
flags by setting ``GNT_NODE_LIST``, ``GNT_GROUP_LIST`` and
``GNT_INSTANCE_LIST``.

Field formatting
----------------

Multiple ganeti commands use the same framework for tabular listing of
resources (e.g. **gnt-instance list**, **gnt-node list**, **gnt-group
list**, **gnt-debug locks**, etc.). For these commands, special states
are denoted via a special symbol (in terse mode) or a string (in
verbose mode):

\*, (offline)
    The node in question is marked offline, and thus it cannot be
    queried for data. This result is persistent until the node is
    de-offlined.

?, (nodata)
    Ganeti expected to receive an answer from this entity, but the
    cluster RPC call failed and/or we didn't receive a valid answer;
    usually more information is available in the node daemon log (if
    the node is alive) or the master daemon log. This result is
    transient, and re-running command might return a different result.

-, (unavail)
    The respective field doesn't make sense for this entity;
    e.g. querying a down instance for its current memory 'live' usage,
    or querying a non-vm_capable node for disk/memory data. This
    result is persistent, and until the entity state is changed via
    ganeti commands, the result won't change.

??, (unknown)
    This field is not known (note that this is different from entity
    being unknown). Either you have mis-typed the field name, or you
    are using a field that the running Ganeti master daemon doesn't
    know. This result is persistent, re-running the command won't
    change it.

Key-value parameters
~~~~~~~~~~~~~~~~~~~~

Multiple options take parameters that are of the form
``key=value,key=value,...`` or ``category:key=value,...``. Examples
are the hypervisor parameters, backend parameters, etc. For these,
it's possible to use values that contain commas by escaping with via a
backslash (which needs two if not single-quoted, due to shell
behaviour)::

  # gnt-instance modify -H kernel_path=an\\,example instance1
  # gnt-instance modify -H kernel_path='an\,example' instance1

Query filters
~~~~~~~~~~~~~

Most commands listing resources (e.g. instances or nodes) support filtering.
The filter language is similar to Python expressions with some elements from
Perl. The language is not generic. Each condition must consist of a field name
and a value (except for boolean checks), a field can not be compared to another
field. Keywords are case-sensitive.

Examples (see below for syntax details):

- List webservers::

    gnt-instance list --filter 'name =* "web*.example.com"'

- List instances with three or six virtual CPUs and whose primary
  nodes reside in groups starting with the string "rack"::

    gnt-instance list --filter
      '(be/vcpus == 3 or be/vcpus == 6) and pnode.group =~ m/^rack/'

- Nodes hosting primary instances::

    gnt-node list --filter 'pinst_cnt != 0'

- Nodes which aren't master candidates::

    gnt-node list --filter 'not master_candidate'

- Short version for globbing patterns::

    gnt-instance list '*.site1' '*.site2'

Syntax in pseudo-BNF::

  <quoted-string> ::= /* String quoted with single or double quotes,
                         backslash for escaping */

  <integer> ::= /* Number in base-10 positional notation */

  <re> ::= /* Regular expression */

  /*
    Modifier "i": Case-insensitive matching, see
    http://docs.python.org/library/re#re.IGNORECASE

    Modifier "s": Make the "." special character match any character,
    including newline, see http://docs.python.org/library/re#re.DOTALL
  */
  <re-modifiers> ::= /* empty */ | i | s

  <value> ::= <quoted-string> | <integer>

  <condition> ::=
    { /* Value comparison */
      <field> { == | != } <value>

      /* Collection membership */
      | <value> [ not ] in <field>

      /* Regular expressions (recognized delimiters
         are "/", "#", "^", and "|"; backslash for escaping)
      */
      | <field> { =~ | !~ } m/<re>/<re-modifiers>

      /* Globbing */
      | <field> { =* | !* } <quoted-string>

      /* Boolean */
      | <field>
    }

  <filter> ::=
    { [ not ] <condition> | ( <filter> ) }
    [ { and | or } <filter> ]

Operators:

*==*
  Equality
*!=*
  Inequality
*=~*
  Pattern match using regular expression
*!~*
  Logically negated from *=~*
*=\**
  Globbing, see **glob**(7), though only * and ? are supported
*!\**
  Logically negated from *=\**
*in*, *not in*
  Collection membership and negation


Common daemon functionality
---------------------------

All Ganeti daemons re-open the log file(s) when sent a SIGHUP signal.
**logrotate**(8) can be used to rotate Ganeti's log files.

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
