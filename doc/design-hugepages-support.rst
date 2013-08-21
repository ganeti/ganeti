===============================
Huge Pages Support for Ganeti
===============================
This is a design document about implementing support for huge pages in
Ganeti. (Please note that Ganeti works with Transparent Huge Pages i.e.
THP and any reference in this document to Huge Pages refers to explicit
Huge Pages).

Current State and Shortcomings:
-------------------------------
The Linux kernel allows using pages of larger size by setting aside a
portion of the memory. Using larger page size may enhance the
performance of applications that require a lot of memory by improving
page hits. To use huge pages, memory has to be reserved beforehand. This
portion of memory is subtracted from free memory and is considered as in
use. Currently Ganeti cannot take proper advantage of huge pages. On a
node, if huge pages are reserved and are available to fulfill the VM
request, Ganeti fails to recognize huge pages and considers the memory
reserved for huge pages as used memory.  This leads to failure of
launching VMs on a node where memory is available in the form of huge
pages rather than normal pages.

Proposed Changes:
-----------------
The following components will be changed in order for Ganeti to take
advantage of Huge Pages.

Hypervisor Parameters:
----------------------
Currently, It is possible to set or modify huge pages mount point at
cluster level via the hypervisor parameter ``mem_path`` as::

	$ gnt-cluster init \
	>--enabled-hypervisors=kvm -nic-parameters link=br100 \
	> -H kvm:mem_path=/mount/point/for/hugepages

This hypervisor parameter is inherited by all the instances as
default although it can be overriden at the instance level.

The following changes will be made to the inheritence behaviour.

-  The hypervisor parameter   ``mem_path`` and all other hypervisor
   parameters will be made available at the node group level (in
   addition to the cluster level), so that users can set defaults for
   the node group::

	$ gnt-group add/modify\
	> -H hv:parameter=value

   This changes the hypervisor inheritence level as::

     cluster -> group -> OS -> instance

-  Furthermore, the hypervisor parameter ``mem_path`` will be changeable
   only at the cluster or node group level and users must not be able to
   override this at OS or instance level. The following command must
   produce an error message that ``mem_path`` may only be set at either
   the cluster or the node group level::

	$ gnt-instance add -H kvm:mem_path=/mount/point/for/hugepages

Memory Pools:
-------------
Memory management of Ganeti will be improved by creating separate pools
for memory used by the node itself, memory used by the hypervisor and
the memory reserved for huge pages as:
- mtotal/xen (Xen memory)
- mfree/xen (Xen unused memory)
- mtotal/hp (Memory reserved for Huge Pages)
- mfree/hp (Memory available from unused huge pages)
- mpgsize/hp (Size of a huge page)

mfree and mtotal will be changed to mean "the total and free memory for
the default method in this cluster/nodegroup". Note that the default
method depends both on the default hypervisor and its parameters.

iAllocator Changes:
-------------------
If huge pages are set as default for a cluster of node group, then
iAllocator must consider the huge pages memory on the nodes, as a
parameter when trying to find the best node for the VM.
Note that the iallocator will also be changed to use the correct
parameter depending on the cluster/group.

hbal Changes:
-------------
The cluster balancer (hbal) will be changed to use the default  memory
pool and  recognize memory reserved for huge pages when trying to
rebalance the cluster.

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
