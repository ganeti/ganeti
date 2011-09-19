Ganeti Node OOB Management Framework
====================================

Objective
---------

Extend Ganeti with Out of Band (:term:`OOB`) Cluster Node Management
Capabilities.

Background
----------

Ganeti currently has no support for Out of Band management of the nodes
in a cluster. It relies on the OS running on the nodes and has therefore
limited possibilities when the OS is not responding. The command
``gnt-node powercycle`` can be issued to attempt a reboot of a node that
crashed but there are no means to power a node off and power it back
on. Supporting this is very handy in the following situations:

  * **Emergency Power Off**: During emergencies, time is critical and
    manual tasks just add latency which can be avoided through
    automation. If a server room overheats, halting the OS on the nodes
    is not enough. The nodes need to be powered off cleanly to prevent
    damage to equipment.
  * **Repairs**: In most cases, repairing a node means that the node has
    to be powered off.
  * **Crashes**: Software bugs may crash a node. Having an OS
    independent way to power-cycle a node helps to recover the node
    without human intervention.

Overview
--------

Ganeti will be extended with OOB capabilities through adding a new
**Cluster Parameter** (``--oob-program``), a new **Node Property**
(``--oob-program``), a new **Node State (powered)** and support in
``gnt-node`` for invoking an **External Helper Command** which executes
the actual OOB command (``gnt-node <command> nodename ...``). The
supported commands are: ``power on``, ``power off``, ``power cycle``,
``power status`` and ``health``.

.. note::
  The new **Node State (powered)** is a **State of Record**
  (:term:`SoR`), not a **State of World** (:term:`SoW`).  The maximum
  execution time of the **External Helper Command** will be limited to
  60s to prevent the cluster from getting locked for an undefined amount
  of time.

Detailed Design
---------------

New ``gnt-cluster`` Parameter
+++++++++++++++++++++++++++++

| Program: ``gnt-cluster``
| Command: ``modify|init``
| Parameters: ``--oob-program``
| Options: ``--oob-program``: executable OOB program (absolute path)

New ``gnt-cluster epo`` Command
+++++++++++++++++++++++++++++++

| Program: ``gnt-cluster``
| Command: ``epo``
| Parameter: ``--on`` ``--force`` ``--groups`` ``--all``
| Options: ``--on``: By default epo turns off, with ``--on`` it tries to get the
|                    cluster back online
|          ``--force``: To force the operation without asking for confirmation
|          ``--groups``: To operate on groups instead of nodes
|          ``--all``: To operate on the whole cluster

This is a convenience command to allow easy emergency power off of a
whole cluster or part of it. It takes care of all steps needed to get
the cluster into a sane state to turn off the nodes.

With ``--on`` it does the reverse and tries to bring the rest of the
cluster back to life.

.. note::
  The master node is not able to shut itself cleanly down. Therefore,
  this command will not do all the work on single node clusters. On
  multi node clusters the command tries to find another master or if
  that is not possible prepares everything to the point where the user
  has to shutdown the master node itself alone this applies also to the
  single node cluster configuration.

New ``gnt-node`` Property
+++++++++++++++++++++++++

| Program: ``gnt-node``
| Command: ``modify|add``
| Parameters: ``--oob-program``
| Options: ``--oob-program``: executable OOB program (absolute path)

.. note::
  If ``--oob-program`` is set to ``!`` then the node has no OOB
  capabilities.  Otherwise, we will inherit the node group respectively
  the cluster wide value. I.e. the nodes have to opt out from OOB
  capabilities.

Addition to ``gnt-cluster verify``
++++++++++++++++++++++++++++++++++

| Program: ``gnt-cluster``
| Command: ``verify``
| Parameter: None
| Option: None
| Additional Checks:

  1. existence and execution flag of OOB program on all Master
     Candidates if the cluster parameter ``--oob-program`` is set or at
     least one node has the property ``--oob-program`` set. The OOB
     helper is just invoked on the master
  2. check if node state powered matches actual power state of the
     machine for those nodes where ``--oob-program`` is set

New Node State
++++++++++++++

Ganeti supports the following two boolean states related to the nodes:

**drained**
  The cluster still communicates with drained nodes but excludes them
  from allocation operations

**offline**
  if offline, the cluster does not communicate with offline nodes;
  useful for nodes that are not reachable in order to avoid delays

And will extend this list with the following boolean state:

**powered**
  if not powered, the cluster does not communicate with not powered
  nodes if the node property ``--oob-program`` is not set, the state
  powered is not displayed

Additionally modify the meaning of the offline state as follows:

**offline**
  if offline, the cluster does not communicate with offline nodes
  (**with the exception of OOB commands for nodes where**
  ``--oob-program`` **is set**); useful for nodes that are not reachable
  in order to avoid delays

The corresponding command extensions are:

| Program: ``gnt-node``
| Command: ``info``
| Parameter:  [ ``nodename`` ... ]
| Option: None

Additional Output (:term:`SoR`, ommited if node property
``--oob-program`` is not set):
powered: ``[True|False]``

| Program: ``gnt-node``
| Command: ``modify``
| Parameter: nodename
| Option: [ ``--powered=yes|no`` ]
| Reasoning: sometimes you will need to sync the :term:`SoR` with the :term:`SoW` manually
| Caveat: ``--powered`` can only be modified if ``--oob-program`` is set for
|         the node in question

New ``gnt-node`` commands: ``power [on|off|cycle|status]``
++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

| Program: ``gnt-node``
| Command: ``power [on|off|cycle|status]``
| Parameters: [ ``nodename`` ... ]
| Options: None
| Caveats:

  * If no nodenames are passed to ``power [on|off|cycle]``, the user
    will be prompted with ``"Do you really want to power [on|off|cycle]
    the following nodes: <display list of OOB capable nodes in the
    cluster)? (y/n)"``
  * For ``power-status``, nodename is optional, if omitted, we list the
    power-status of all OOB capable nodes in the cluster (:term:`SoW`)
  * User should be warned and needs to confirm with yes if s/he tries to
    ``power [off|cycle]`` a node with running instances.

Error Handling
^^^^^^^^^^^^^^

+-----------------------------+----------------------------------------------+
| Exception                   | Error Message                                |
+=============================+==============================================+
| OOB program return code != 0| OOB program execution failed ($ERROR_MSG)    |
+-----------------------------+----------------------------------------------+
| OOB program execution time  | OOB program execution timeout exceeded, OOB  |
| exceeds 60s                 | program execution aborted                    |
+-----------------------------+----------------------------------------------+

Node State Changes
^^^^^^^^^^^^^^^^^^

+----------------+---------------+----------------+--------------------------+
| State before   |Command        | State after    | Comment                  |
| execution      |               | execution      |                          |
+================+===============+================+==========================+
| powered: False |``power off``  | powered: False | FYI: IPMI will complain  |
|                |               |                | if you try to power off  |
|                |               |                | a machine that is already|
|                |               |                | powered off              |
+----------------+---------------+----------------+--------------------------+
| powered: False |``power cycle``| powered: False | FYI: IPMI will complain  |
|                |               |                | if you try to cycle a    |
|                |               |                | machine that is already  |
|                |               |                | powered off              |
+----------------+---------------+----------------+--------------------------+
| powered: False |``power on``   | powered: True  |                          |
+----------------+---------------+----------------+--------------------------+
| powered: True  |``power off``  | powered: False |                          |
+----------------+---------------+----------------+--------------------------+
| powered: True  |``power cycle``| powered: True  |                          |
+----------------+---------------+----------------+--------------------------+
| powered: True  |``power on``   | powered: True  | FYI: IPMI will complain  |
|                |               |                | if you try to power on   |
|                |               |                | a machine that is already|
|                |               |                | powered on               |
+----------------+---------------+----------------+--------------------------+

.. note::

  * If the command fails, the Node State remains unchanged.
  * We will not prevent the user from trying to power off a node that is
    already powered off since the powered state represents the
    :term:`SoR` only and not the :term:`SoW`. This can however create
    problems when the cluster administrator wants to bring the
    :term:`SoR` in sync with the :term:SoW` without actually having to
    mess with the node(s). For this case, we allow direct modification
    of the powered state through the gnt-node modify
    ``--powered=[yes|no]`` command as long as the node has OOB
    capabilities (i.e. ``--oob-program`` is set).
  * All node power state changes will be logged

Node Power Status Listing (:term:`SoW`)
+++++++++++++++++++++++++++++++++++++++

| Program: ``gnt-node``
| Command: ``power-status``
| Parameters: [ ``nodename`` ... ]

Example output (represents :term:`SoW`)::

  gnt-node oob power-status
  Node                      Power Status
  node1.example.com         on
  node2.example.com         off
  node3.example.com         on
  node4.example.com         unknown

.. note::

  * We use ``unknown`` in case the Helper Program could not determine
    the power state.
  * If no nodenames are provided, we will list the power state of all
    nodes which are not opted out from OOB management.
  * Only nodes which are not opted out from OOB management will be
    listed.  Invoking the command on a node that does not meet this
    condition will result in an error message "Node X does not support
    OOB commands".

Node Power Status Listing (:term:`SoR`)
+++++++++++++++++++++++++++++++++++++++

| Program: ``gnt-node``
| Command: ``info``
| Parameter:  [ ``nodename`` ... ]
| Option: None

Example output (represents :term:`SoR`)::

  gnt-node info node1.example.com
  Node name: node1.example.com
    primary ip: 192.168.1.1
    secondary ip: 192.168.2.1
    master candidate: True
    drained: False
    offline: False
    powered: True
    primary for instances:
      - inst1.example.com
      - inst2.example.com
      - inst3.example.com
    secondary for instances:
      - inst4.example.com
      - inst5.example.com
      - inst6.example.com
      - inst7.example.com

.. note::
  Only nodes which are not opted out from OOB management will report the
  powered state.

New ``gnt-node`` oob subcommand: ``health``
+++++++++++++++++++++++++++++++++++++++++++

| Program: ``gnt-node``
| Command: ``health``
| Parameters: [ ``nodename`` ... ]
| Options: None
| Example: ``/usr/bin/oob health node5.example.com``

Caveats:

  * If no nodename(s) are provided, we will report the health of all
    nodes in the cluster which have ``--oob-program`` set.
  * Only nodes which are not opted out from OOB management will report
    their health. Invoking the command on a node that does not meet this
    condition will result in an error message "Node does not support OOB
    commands".

For error handling see `Error Handling`_

OOB Program (Helper Program) Parameters, Return Codes and Data Format
+++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

| Program: executable OOB program (absolute path)
| Parameters: command nodename
| Command: [power-{on|off|cycle|status}|health]
| Options: None
| Example: ``/usr/bin/oob power-on node1.example.com``
| Caveat: maximum runtime is limited to 60s

Return Codes
^^^^^^^^^^^^

+-------------+-------------------------+
| Return code | Meaning                 |
+=============+=========================+
| 0           | Command succeeded       |
+-------------+-------------------------+
| 1           | Command failed          |
+-------------+-------------------------+
| others      | Unsupported/undefined   |
+-------------+-------------------------+

Error messages are passed from the helper program to Ganeti through
:manpage:`stderr(3)` (return code == 1).  On :manpage:`stdout(3)`, the
helper program will send data back to Ganeti (return code == 0). The
format of the data is JSON.

+-----------------+------------------------------+
| Command         | Expected output              |
+=================+==============================+
| ``power-on``    | None                         |
+-----------------+------------------------------+
| ``power-off``   | None                         |
+-----------------+------------------------------+
| ``power-cycle`` | None                         |
+-----------------+------------------------------+
| ``power-status``| ``{ "powered": true|false }``|
+-----------------+------------------------------+
| ``health``      | ::                           |
|                 |                              |
|                 |   [[item, status],           |
|                 |    [item, status],           |
|                 |    ...]                      |
+-----------------+------------------------------+

Data Format
^^^^^^^^^^^

For the health output, the fields are:

+--------+------------------------------------------------------------------+
| Field  | Meaning                                                          |
+========+==================================================================+
| item   | String identifier of the item we are querying the health of,     |
|        | examples:                                                        |
|        |                                                                  |
|        |   * Ambient Temp                                                 |
|        |   * PS Redundancy                                                |
|        |   * FAN 1 RPM                                                    |
+--------+------------------------------------------------------------------+
| status | String; Can take one of the following four values:               |
|        |                                                                  |
|        |   * OK                                                           |
|        |   * WARNING                                                      |
|        |   * CRITICAL                                                     |
|        |   * UNKNOWN                                                      |
+--------+------------------------------------------------------------------+

.. note::

  * The item output list is defined by the Helper Program. It is up to
    the author of the Helper Program to decide which items should be
    monitored and what each corresponding return status is.
  * Ganeti will currently not take any actions based on the item
    status. It will however create log entries for items with status
    WARNING or CRITICAL for each run of the ``gnt-node oob health
    nodename`` command. Automatic actions (regular monitoring of the
    item status) is considered a new service and will be treated in a
    separate design document.

Logging
-------

The ``gnt-node power-[on|off]`` (power state changes) commands will
create log entries following current Ganeti logging practices. In
addition, health items with status WARNING or CRITICAL will be logged
for each run of ``gnt-node health``.

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
