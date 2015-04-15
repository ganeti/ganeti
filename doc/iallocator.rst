Ganeti automatic instance allocation
====================================

Documents Ganeti version 2.16

.. contents::

Introduction
------------

Currently in Ganeti the admin has to specify the exact locations for
an instance's node(s). This prevents a completely automatic node
evacuation, and is in general a nuisance.

The *iallocator* framework will enable automatic placement via
external scripts, which allows customization of the cluster layout per
the site's requirements.

User-visible changes
~~~~~~~~~~~~~~~~~~~~

There are two parts of the ganeti operation that are impacted by the
auto-allocation: how the cluster knows what the allocator algorithms
are and how the admin uses these in creating instances.

An allocation algorithm is just the filename of a program installed in
a defined list of directories.

Cluster configuration
~~~~~~~~~~~~~~~~~~~~~

At configure time, the list of the directories can be selected via the
``--with-iallocator-search-path=LIST`` option, where *LIST* is a
comma-separated list of directories. If not given, this defaults to
``$libdir/ganeti/iallocators``, i.e. for an installation under
``/usr``, this will be ``/usr/lib/ganeti/iallocators``.

Ganeti will then search for allocator script in the configured list,
using the first one whose filename matches the one given by the user.

Command line interface changes
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The node selection options in instance add and instance replace disks
can be replace by the new ``--iallocator=NAME`` option (shortened to
``-I``), which will cause the auto-assignement of nodes with the
passed iallocator. The selected node(s) will be shown as part of the
command output.

IAllocator API
--------------

The protocol for communication between Ganeti and an allocator script
will be the following:

#. ganeti launches the program with a single argument, a filename that
   contains a JSON-encoded structure (the input message)

#. if the script finishes with exit code different from zero, it is
   considered a general failure and the full output will be reported to
   the users; this can be the case when the allocator can't parse the
   input message

#. if the allocator finishes with exit code zero, it is expected to
   output (on its stdout) a JSON-encoded structure (the response)

Input message
~~~~~~~~~~~~~

The input message will be the JSON encoding of a dictionary containing
all the required information to perform the operation. We explain the
contents of this dictionary in two parts: common information that every
type of operation requires, and operation-specific information.

Common information
++++++++++++++++++

All input dictionaries to the IAllocator must carry the following keys:

version
  the version of the protocol; this document
  specifies version 2

cluster_name
  the cluster name

cluster_tags
  the list of cluster tags

enabled_hypervisors
  the list of enabled hypervisors

ipolicy
  the cluster-wide instance policy (for information; the per-node group
  values take precedence and should be used instead)

request
  a dictionary containing the details of the request; the keys vary
  depending on the type of operation that's being requested, as
  explained in `Operation-specific input`_ below.

nodegroups
  a dictionary with the data for the cluster's node groups; it is keyed
  on the group UUID, and the values are a dictionary with the following
  keys:

  name
    the node group name
  alloc_policy
    the allocation policy of the node group (consult the semantics of
    this attribute in the :manpage:`gnt-group(8)` manpage)
  networks
    the list of network UUID's this node group is connected to
  ipolicy
    the instance policy of the node group
  tags
    the list of node group tags

instances
  a dictionary with the data for the current existing instance on the
  cluster, indexed by instance name; the contents are similar to the
  instance definitions for the allocate mode, with the addition of:

  admin_state
    if this instance is set to run (but not the actual status of the
    instance)

  nodes
    list of nodes on which this instance is placed; the primary node
    of the instance is always the first one

nodes
  dictionary with the data for the nodes in the cluster, indexed by
  the node name; the dict contains [*]_ :

  total_disk
    the total disk size of this node (mebibytes)

  free_disk
    the free disk space on the node

  total_memory
    the total memory size

  free_memory
    free memory on the node; note that currently this does not take
    into account the instances which are down on the node

  total_cpus
    the physical number of CPUs present on the machine; depending on
    the hypervisor, this might or might not be equal to how many CPUs
    the node operating system sees;

  primary_ip
    the primary IP address of the node

  secondary_ip
    the secondary IP address of the node (the one used for the DRBD
    replication); note that this can be the same as the primary one

  tags
    list with the tags of the node

  master_candidate:
    a boolean flag denoting whether this node is a master candidate

  drained:
    a boolean flag denoting whether this node is being drained

  offline:
    a boolean flag denoting whether this node is offline

  i_pri_memory:
    total memory required by primary instances

  i_pri_up_memory:
    total memory required by running primary instances

  group:
    the node group that this node belongs to

  No allocations should be made on nodes having either the ``drained``
  or ``offline`` flags set. More details about these of node status
  flags is available in the manpage :manpage:`ganeti(7)`.

.. [*] Note that no run-time data is present for offline, drained or
   non-vm_capable nodes; this means the tags total_memory,
   reserved_memory, free_memory, total_disk, free_disk, total_cpus,
   i_pri_memory and i_pri_up memory will be absent

Operation-specific input
++++++++++++++++++++++++

All input dictionaries to the IAllocator carry, in the ``request``
dictionary, detailed information about the operation that's being
requested. The required keys vary depending on the type of operation, as
follows.

In all cases, it includes:

  type
    the request type; this can be either ``allocate``, ``relocate``,
    ``change-group`` or ``node-evacuate``. The
    ``allocate`` request is used when a new instance needs to be placed
    on the cluster. The ``relocate`` request is used when an existing
    instance needs to be moved within its node group.

    The ``multi-evacuate`` protocol used to request that the script
    computes the optimal relocate solution for all secondary instances
    of the given nodes. It is now deprecated and needs only be
    implemented if backwards compatibility with Ganeti 2.4 and lower is
    needed.

    The ``change-group`` request is used to relocate multiple instances
    across multiple node groups. ``node-evacuate`` evacuates instances
    off their node(s). These are described in a separate :ref:`design
    document <multi-reloc-detailed-design>`.

    The ``multi-allocate`` request is used to allocate multiple
    instances on the cluster. The request is beside of that very
    similiar to the ``allocate`` one. For more details look at
    :doc:`Ganeti bulk create <design-bulk-create>`.

For both allocate and relocate mode, the following extra keys are needed
in the ``request`` dictionary:

  name
    the name of the instance; if the request is a realocation, then this
    name will be found in the list of instances (see below), otherwise
    is the FQDN of the new instance; type *string*

  required_nodes
    how many nodes should the algorithm return; while this information
    can be deduced from the instace's disk template, it's better if
    this computation is left to Ganeti as then allocator scripts are
    less sensitive to changes to the disk templates; type *integer*

  disk_space_total
    the total disk space that will be used by this instance on the
    (new) nodes; again, this information can be computed from the list
    of instance disks and its template type, but Ganeti is better
    suited to compute it; type *integer*

.. pyassert::

   constants.DISK_ACCESS_SET == set([constants.DISK_RDONLY,
     constants.DISK_RDWR])

Allocation needs, in addition:

  disks
    list of dictionaries holding the disk definitions for this
    instance (in the order they are exported to the hypervisor):

    mode
      either :pyeval:`constants.DISK_RDONLY` or
      :pyeval:`constants.DISK_RDWR` denoting if the disk is read-only or
      writable

    size
      the size of this disk in mebibytes

  nics
    a list of dictionaries holding the network interfaces for this
    instance, containing:

    ip
      the IP address that Ganeti know for this instance, or null

    mac
      the MAC address for this interface

    bridge
      the bridge to which this interface will be connected

  vcpus
    the number of VCPUs for the instance

  disk_template
    the disk template for the instance

  memory
   the memory size for the instance

  os
   the OS type for the instance

  tags
    the list of the instance's tags

  hypervisor
    the hypervisor of this instance

Relocation:

  relocate_from
     a list of nodes to move the instance away from; for DRBD-based
     instances, this will contain a single node, the current secondary
     of the instance, whereas for shared-storage instance, this will
     contain also a single node, the current primary of the instance;
     type *list of strings*

As for ``node-evacuate``, it needs the following request arguments:

  instances
    a list of instance names to evacuate; type *list of strings*

  evac_mode
    specify which instances to evacuate; one of ``primary-only``,
    ``secondary-only``, ``all``, type *string*

``change-group`` needs the following request arguments:

  instances
    a list of instance names whose group to change; type
    *list of strings*

  target_groups
    must either be the empty list, or contain a list of group UUIDs that
    should be considered for relocating instances to; type
    *list of strings*

``multi-allocate`` needs the following request arguments:

  instances
    a list of request dicts

MonD data
+++++++++

Additional information is available from mond. Mond's data collectors
provide information that can help an allocator script make better
decisions when allocating a new instance. Mond's information may also be
accessible from a mock file mainly for testing purposes. The file will
be in JSON format and will present an array of :ref:`report objects
<monitoring-agent-format-of-the-report>`.

Response message
~~~~~~~~~~~~~~~~

The response message is much more simple than the input one. It is
also a dict having three keys:

success
  a boolean value denoting if the allocation was successful or not

info
  a string with information from the scripts; if the allocation fails,
  this will be shown to the user

result
  the output of the algorithm; even if the algorithm failed
  (i.e. success is false), this must be returned as an empty list

  for allocate/relocate, this is the list of node(s) for the instance;
  note that the length of this list must equal the ``requested_nodes``
  entry in the input message, otherwise Ganeti will consider the result
  as failed

  for the ``node-evacuate`` and ``change-group`` modes, this is a
  dictionary containing, among other information, a list of lists of
  serialized opcodes; see the :ref:`design document
  <multi-reloc-result>` for a detailed description

  for the ``multi-allocate`` mode this is a tuple of 2 lists, the first
  being element of the tuple is a list of succeeded allocation, with the
  instance name as first element of each entry and the node placement in
  the second. The second element of the tuple is the instance list of
  failed allocations.

.. note:: Current Ganeti version accepts either ``result`` or ``nodes``
   as a backwards-compatibility measure (older versions only supported
   ``nodes``)

Examples
--------

Input messages to scripts
~~~~~~~~~~~~~~~~~~~~~~~~~

Input message, new instance allocation (common elements are listed this
time, but not included in further examples below)::

  {
    "version": 2,
    "cluster_name": "cluster1.example.com",
    "cluster_tags": [],
    "enabled_hypervisors": [
      "xen-pvm"
    ],
    "nodegroups": {
      "f4e06e0d-528a-4963-a5ad-10f3e114232d": {
        "name": "default",
        "alloc_policy": "preferred",
        "networks": ["net-uuid-1", "net-uuid-2"],
        "ipolicy": {
          "disk-templates": ["drbd", "plain"],
          "minmax": [
            {
              "max": {
                "cpu-count": 2,
                "disk-count": 8,
                "disk-size": 2048,
                "memory-size": 12800,
                "nic-count": 8,
                "spindle-use": 8
              },
              "min": {
                "cpu-count": 1,
                "disk-count": 1,
                "disk-size": 1024,
                "memory-size": 128,
                "nic-count": 1,
                "spindle-use": 1
              }
            }
          ],
          "spindle-ratio": 32.0,
          "std": {
            "cpu-count": 1,
            "disk-count": 1,
            "disk-size": 1024,
            "memory-size": 128,
            "nic-count": 1,
            "spindle-use": 1
          },
          "vcpu-ratio": 4.0
        },
        "tags": ["ng-tag-1", "ng-tag-2"]
      }
    },
    "instances": {
      "instance1.example.com": {
        "tags": [],
        "should_run": false,
        "disks": [
          {
            "mode": "w",
            "size": 64
          },
          {
            "mode": "w",
            "size": 512
          }
        ],
        "nics": [
          {
            "ip": null,
            "mac": "aa:00:00:00:60:bf",
            "bridge": "xen-br0"
          }
        ],
        "vcpus": 1,
        "disk_template": "plain",
        "memory": 128,
        "nodes": [
          "nodee1.com"
        ],
        "os": "debootstrap+default"
      },
      "instance2.example.com": {
        "tags": [],
        "should_run": false,
        "disks": [
          {
            "mode": "w",
            "size": 512
          },
          {
            "mode": "w",
            "size": 256
          }
        ],
        "nics": [
          {
            "ip": null,
            "mac": "aa:00:00:55:f8:38",
            "bridge": "xen-br0"
          }
        ],
        "vcpus": 1,
        "disk_template": "drbd",
        "memory": 512,
        "nodes": [
          "node2.example.com",
          "node3.example.com"
        ],
        "os": "debootstrap+default"
      }
    },
    "nodes": {
      "node1.example.com": {
        "total_disk": 858276,
        "primary_ip": "198.51.100.1",
        "secondary_ip": "192.0.2.1",
        "tags": [],
        "group": "f4e06e0d-528a-4963-a5ad-10f3e114232d",
        "free_memory": 3505,
        "free_disk": 856740,
        "total_memory": 4095
      },
      "node2.example.com": {
        "total_disk": 858240,
        "primary_ip": "198.51.100.2",
        "secondary_ip": "192.0.2.2",
        "tags": ["test"],
        "group": "f4e06e0d-528a-4963-a5ad-10f3e114232d",
        "free_memory": 3505,
        "free_disk": 848320,
        "total_memory": 4095
      },
      "node3.example.com.com": {
        "total_disk": 572184,
        "primary_ip": "198.51.100.3",
        "secondary_ip": "192.0.2.3",
        "tags": [],
        "group": "f4e06e0d-528a-4963-a5ad-10f3e114232d",
        "free_memory": 3505,
        "free_disk": 570648,
        "total_memory": 4095
      }
    },
    "request": {
      "type": "allocate",
      "name": "instance3.example.com",
      "required_nodes": 2,
      "disk_space_total": 3328,
      "disks": [
        {
          "mode": "w",
          "size": 1024
        },
        {
          "mode": "w",
          "size": 2048
        }
      ],
      "nics": [
        {
          "ip": null,
          "mac": "00:11:22:33:44:55",
          "bridge": null
        }
      ],
      "vcpus": 1,
      "disk_template": "drbd",
      "memory": 2048,
      "os": "debootstrap+default",
      "tags": [
        "type:test",
        "owner:foo"
      ],
      hypervisor: "xen-pvm"
    }
  }

Input message, reallocation::

  {
    "version": 2,
    ...
    "request": {
      "type": "relocate",
      "name": "instance2.example.com",
      "required_nodes": 1,
      "disk_space_total": 832,
      "relocate_from": [
        "node3.example.com"
      ]
    }
  }


Response messages
~~~~~~~~~~~~~~~~~
Successful response message::

  {
    "success": true,
    "info": "Allocation successful",
    "result": [
      "node2.example.com",
      "node1.example.com"
    ]
  }

Failed response message::

  {
    "success": false,
    "info": "Can't find a suitable node for position 2 (already selected: node2.example.com)",
    "result": []
  }

Successful node evacuation message::

  {
    "success": true,
    "info": "Request successful",
    "result": [
      [
        "instance1",
        "node3"
      ],
      [
        "instance2",
        "node1"
      ]
    ]
  }


Command line messages
~~~~~~~~~~~~~~~~~~~~~
::

  # gnt-instance add -t plain -m 2g --os-size 1g --swap-size 512m --iallocator hail -o debootstrap+default instance3
  Selected nodes for the instance: node1.example.com
  * creating instance disks...
  [...]

  # gnt-instance add -t plain -m 3400m --os-size 1g --swap-size 512m --iallocator hail -o debootstrap+default instance4
  Failure: prerequisites not met for this operation:
  Can't compute nodes using iallocator 'hail': Can't find a suitable node for position 1 (already selected: )

  # gnt-instance add -t drbd -m 1400m --os-size 1g --swap-size 512m --iallocator hail -o debootstrap+default instance5
  Failure: prerequisites not met for this operation:
  Can't compute nodes using iallocator 'hail': Can't find a suitable node for position 2 (already selected: node1.example.com)

Reference implementation
~~~~~~~~~~~~~~~~~~~~~~~~

Ganeti's default iallocator is "hail" which is available when "htools"
components have been enabled at build time (see :doc:`install-quick` for
more details).

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
