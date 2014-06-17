Ganeti CPU Pinning
==================

Objective
---------

This document defines Ganeti's support for CPU pinning (aka CPU
affinity).

CPU pinning enables mapping and unmapping entire virtual machines or a
specific virtual CPU (vCPU), to a physical CPU or a range of CPUs.

At this stage Pinning will be implemented for Xen and KVM.

Command Line
------------

Suggested command line parameters for controlling CPU pinning are as
follows::

  gnt-instance modify -H cpu_mask=<cpu-pinning-info> <instance>

cpu-pinning-info can be any of the following:

* One vCPU mapping, which can be the word "all" or a combination
  of CPU numbers and ranges separated by comma. In this case, all
  vCPUs will be mapped to the indicated list.
* A list of vCPU mappings, separated by a colon ':'. In this case
  each vCPU is mapped to an entry in the list, and the size of the
  list must match the number of vCPUs defined for the instance. This
  is enforced when setting CPU pinning or when setting the number of
  vCPUs using ``-B vcpus=#``.

  The mapping list is matched to consecutive virtual CPUs, so the first entry
  would be the CPU pinning information for vCPU 0, the second entry
  for vCPU 1, etc.

The default setting for new instances is "all", which maps the entire
instance to all CPUs, thus effectively turning off CPU pinning.

Here are some usage examples::

  # Map vCPU 0 to physical CPU 1 and vCPU 1 to CPU 3 (assuming 2 vCPUs)
  gnt-instance modify -H cpu_mask=1:3 my-inst

  # Pin vCPU 0 to CPUs 1 or 2, and vCPU 1 to any CPU
  gnt-instance modify -H cpu_mask=1-2:all my-inst

  # Pin vCPU 0 to any CPU, vCPU 1 to CPUs 1, 3, 4 or 5, and CPU 2 to
  # CPU 0
  gnt-instance modify -H cpu_mask=all:1\\,3-5:0 my-inst

  # Pin entire VM to CPU 0
  gnt-instance modify -H cpu_mask=0 my-inst

  # Turn off CPU pinning (default setting)
  gnt-instance modify -H cpu_mask=all my-inst

Assuming an instance has 3 vCPUs, the following commands will fail::

  # not enough mappings
  gnt-instance modify -H cpu_mask=0:1 my-inst

  # too many
  gnt-instance modify -H cpu_mask=2:1:1:all my-inst

Validation
----------

CPU pinning information is validated by making sure it matches the
number of vCPUs. This validation happens when changing either the
cpu_mask or vcpus parameters.
Changing either parameter in a way that conflicts with the other will
fail with a proper error message.
To make such a change, both parameters should be modified at the same
time. For example:
``gnt-instance modify -B vcpus=4 -H cpu_mask=1:1:2-3:4\\,6 my-inst``

Besides validating CPU configuration, i.e. the number of vCPUs matches
the requested CPU pinning, Ganeti will also verify the number of
physical CPUs is enough to support the required configuration. For
example, trying to run a configuration of vcpus=2,cpu_mask=0:4 on
a node with 4 cores will fail (Note: CPU numbers are 0-based).

This validation should repeat every time an instance is started or
migrated live. See more details under Migration below.

Cluster verification should also test the compatibility of other nodes in
the cluster to required configuration and alert if a minimum requirement
is not met.

Failover
--------

CPU pinning configuration can be transferred from node to node, unless
the number of physical CPUs is smaller than what the configuration calls
for.  It is suggested that unless this is the case, all transfers and
migrations will succeed.

In case the number of physical CPUs is smaller than the numbers
indicated by CPU pinning information, instance failover will fail.

In case of emergency, to force failover to ignore mismatching CPU
information, the following switch can be used:
``gnt-instance failover --fix-cpu-mismatch my-inst``.
This command will try to failover the instance with the current cpu mask,
but if that fails, it will change the mask to be "all".

Migration
---------

In case of live migration, and in addition to failover considerations,
it is required to remap CPU pinning after migration. This can be done in
realtime for instances for both Xen and KVM, and only depends on the
number of physical CPUs being sufficient to support the migrated
instance.

Data
----

Pinning information will be kept as a list of integers per vCPU.
To mark a mapping of any CPU, we will use (-1).
A single entry, no matter what the number of vCPUs is, will always mean
that all vCPUs have the same mapping.

Configuration file
------------------

The pinning information is kept for each instance's hypervisor
params section of the configuration file as the original string.

Xen
---

There are 2 ways to control pinning in Xen, either via the command line
or through the configuration file.

The commands to make direct pinning changes are the following::

  # To pin a vCPU to a specific CPU
  xm vcpu-pin <domain> <vcpu> <cpu>

  # To unpin a vCPU
  xm vcpu-pin <domain> <vcpu> all

  # To get the current pinning status
  xm vcpu-list <domain>

Since currently controlling Xen in Ganeti is done in the configuration
file, it is straight forward to use the same method for CPU pinning.
There are 2 different parameters that control Xen's CPU pinning and
configuration:

vcpus
  controls the number of vCPUs
cpus
  maps vCPUs to physical CPUs

When no pinning is required (pinning information is "all"), the
"cpus" entry is removed from the configuration file.

For all other cases, the configuration is "translated" to Xen, which
expects either ``cpus = "a"`` or ``cpus = [ "a", "b", "c", ...]``,
where each a, b or c are a physical CPU number, CPU range, or a
combination, and the number of entries (if a list is used) must match
the number of vCPUs, and are mapped in order.

For example, CPU pinning information of ``1:2,4-7:0-1`` is translated
to this entry in Xen's configuration ``cpus = [ "1", "2,4-7", "0-1" ]``

KVM
---

Controlling pinning in KVM is a little more complicated as there is no
configuration to control pinning before instances are started.

The way to change or assign CPU pinning under KVM is to use ``taskset`` or
its underlying system call ``sched_setaffinity``. Setting the affinity for
the VM process will change CPU pinning for the entire VM, and setting it
for specific vCPU threads will control specific vCPUs.

The sequence of commands to control pinning is this: start the instance
with the ``-S`` switch, so it halts before starting execution, get the
process ID or identify thread IDs of each vCPU by sending ``info cpus``
to the monitor, map vCPUs as required by the cpu-pinning information,
and issue a ``cont`` command on the KVM monitor to allow the instance
to start execution.

For example, a sequence of commands to control CPU affinity under KVM
may be:

* Start KVM: ``/usr/bin/kvm … <kvm-command-line-options> … -S``
* Use socat to connect to monitor
* send ``info cpus`` to monitor to get thread/vCPU information
* call ``sched_setaffinity`` for each thread with the CPU mask
* send ``cont`` to KVM's monitor

A CPU mask is a hexadecimal bit mask where each bit represents one
physical CPU. See man page for :manpage:`sched_setaffinity(2)` for more
details.

For example, to run a specific thread-id on CPUs 1 or 3 the mask is
0x0000000A.

As of 2.12, the psutil python package
(https://github.com/giampaolo/psutil) will be used to control process
and thread affinity. The affinity python package
(http://pypi.python.org/pypi/affinity) was used before, but it was not
invoking the two underlying system calls appropriately, using a cast
instead of the CPU_SET macro, causing failures for masks referencing
more than 63 CPUs.

Alternative Design Options
--------------------------

1. There's an option to ignore the limitations of the underlying
   hypervisor and instead of requiring explicit pinning information
   for *all* vCPUs, assume a mapping of "all" to vCPUs not mentioned.
   This can lead to inadvertent missing information, but either way,
   since using cpu-pinning options is probably not going to be
   frequent, there's no real advantage.

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
