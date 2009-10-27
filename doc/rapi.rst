Ganeti remote API
=================

Documents Ganeti version |version|

.. contents::

Introduction
------------

Ganeti supports a remote API for enable external tools to easily
retrieve information about a cluster's state. The remote API daemon,
*ganeti-rapi*, is automatically started on the master node. By default
it runs on TCP port 5080, but this can be changed either in
``.../constants.py`` or via the command line parameter *-p*. SSL mode,
which is used by default, can also be disabled by passing command line
parameters.

Protocol
--------

The protocol used is JSON_ over HTTP designed after the REST_
principle.

.. _JSON: http://www.json.org/
.. _REST: http://en.wikipedia.org/wiki/Representational_State_Transfer

Generic parameters
------------------

A few parameter mean the same thing across all resources which implement
it.

``bulk``
++++++++

Bulk-mode means that for the resources which usually return just a list
of child resources (e.g. ``/2/instances`` which returns just instance
names), the output will instead contain detailed data for all these
subresources. This is more efficient than query-ing the sub-resources
themselves.

``dry-run``
+++++++++++

The optional *dry-run* argument, if provided and set to a positive
integer value (e.g. ``?dry-run=1``), signals to Ganeti that the job
should not be executed, only the pre-execution checks will be done.

This is useful in trying to determine (without guarantees though, as in
the meantime the cluster state could have changed) if the operation is
likely to succeed or at least start executing.

``force``
+++++++++++

Force operation to continue even if it will cause the cluster to become
inconsistent (e.g. because there are not enough master candidates).

Usage examples
--------------

You can access the API using your favorite programming language as long
as it supports network connections.

Shell
+++++

.. highlight:: sh

Using wget::

   wget -q -O - https://CLUSTERNAME:5080/2/info

or curl::

  curl https://CLUSTERNAME:5080/2/info


Python
++++++

.. highlight:: python

::

  import urllib2
  f = urllib2.urlopen('https://CLUSTERNAME:5080/2/info')
  print f.read()


JavaScript
++++++++++

.. warning:: While it's possible to use JavaScript, it poses several
   potential problems, including browser blocking request due to
   non-standard ports or different domain names. Fetching the data on
   the webserver is easier.

.. highlight:: javascript

::

  var url = 'https://CLUSTERNAME:5080/2/info';
  var info;
  var xmlreq = new XMLHttpRequest();
  xmlreq.onreadystatechange = function () {
    if (xmlreq.readyState != 4) return;
    if (xmlreq.status == 200) {
      info = eval("(" + xmlreq.responseText + ")");
      alert(info);
    } else {
      alert('Error fetching cluster info');
    }
    xmlreq = null;
  };
  xmlreq.open('GET', url, true);
  xmlreq.send(null);

Resources
---------

.. highlight:: javascript

``/``
+++++

The root resource.

It supports the following commands: ``GET``.

``GET``
~~~~~~~

Shows the list of mapped resources.

Returns: a dictionary with 'name' and 'uri' keys for each of them.

``/2``
++++++

The ``/2`` resource, the root of the version 2 API.

It supports the following commands: ``GET``.

``GET``
~~~~~~~

Show the list of mapped resources.

Returns: a dictionary with ``name`` and ``uri`` keys for each of them.

``/2/info``
+++++++++++

Cluster information resource.

It supports the following commands: ``GET``.

``GET``
~~~~~~~

Returns cluster information.

Example::

  {
    "config_version": 2000000,
    "name": "cluster",
    "software_version": "2.0.0~beta2",
    "os_api_version": 10,
    "export_version": 0,
    "candidate_pool_size": 10,
    "enabled_hypervisors": [
      "fake"
    ],
    "hvparams": {
      "fake": {}
     },
    "default_hypervisor": "fake",
    "master": "node1.example.com",
    "architecture": [
      "64bit",
      "x86_64"
    ],
    "protocol_version": 20,
    "beparams": {
      "default": {
        "auto_balance": true,
        "vcpus": 1,
        "memory": 128
       }
      }
    }


``/2/redistribute-config``
++++++++++++++++++++++++++

Redistribute configuration to all nodes.

It supports the following commands: ``PUT``.

``PUT``
~~~~~~~

Redistribute configuration to all nodes. The result will be a job id.


``/2/instances``
++++++++++++++++

The instances resource.

It supports the following commands: ``GET``, ``POST``.

``GET``
~~~~~~~

Returns a list of all available instances.

Example::

    [
      {
        "name": "web.example.com",
        "uri": "\/instances\/web.example.com"
      },
      {
        "name": "mail.example.com",
        "uri": "\/instances\/mail.example.com"
      }
    ]

If the optional *bulk* argument is provided and set to a true value (i.e
``?bulk=1``), the output contains detailed information about instances
as a list.

Example::

    [
      {
         "status": "running",
         "disk_usage": 20480,
         "nic.bridges": [
           "xen-br0"
          ],
         "name": "web.example.com",
         "tags": ["tag1", "tag2"],
         "beparams": {
           "vcpus": 2,
           "memory": 512
         },
         "disk.sizes": [
             20480
         ],
         "pnode": "node1.example.com",
         "nic.macs": ["01:23:45:67:89:01"],
         "snodes": ["node2.example.com"],
         "disk_template": "drbd",
         "admin_state": true,
         "os": "debian-etch",
         "oper_state": true
      },
      ...
    ]


``POST``
~~~~~~~~

Creates an instance.

If the optional *dry-run* argument is provided and set to a positive
integer valu (e.g. ``?dry-run=1``), the job will not be actually
executed, only the pre-execution checks will be done. Query-ing the job
result will return, in both dry-run and normal case, the list of nodes
selected for the instance.

Returns: a job ID that can be used later for polling.

``/2/instances/[instance_name]``
++++++++++++++++++++++++++++++++

Instance-specific resource.

It supports the following commands: ``GET``, ``DELETE``.

``GET``
~~~~~~~

Returns information about an instance, similar to the bulk output from
the instance list.

``DELETE``
~~~~~~~~~~

Deletes an instance.

It supports the ``dry-run`` argument.


``/2/instances/[instance_name]/info``
+++++++++++++++++++++++++++++++++++++++

It supports the following commands: ``GET``.

``GET``
~~~~~~~

Requests detailed information about the instance. An optional parameter,
``static`` (bool), can be set to return only static information from the
configuration without querying the instance's nodes. The result will be
a job id.


``/2/instances/[instance_name]/reboot``
+++++++++++++++++++++++++++++++++++++++

Reboots URI for an instance.

It supports the following commands: ``POST``.

``POST``
~~~~~~~~

Reboots the instance.

The URI takes optional ``type=hard|soft|full`` and
``ignore_secondaries=False|True`` parameters.

It supports the ``dry-run`` argument.


``/2/instances/[instance_name]/shutdown``
+++++++++++++++++++++++++++++++++++++++++

Instance shutdown URI.

It supports the following commands: ``PUT``.

``PUT``
~~~~~~~

Shutdowns an instance.

It supports the ``dry-run`` argument.


``/2/instances/[instance_name]/startup``
++++++++++++++++++++++++++++++++++++++++

Instance startup URI.

It supports the following commands: ``PUT``.

``PUT``
~~~~~~~

Startup an instance.

The URI takes an optional ``force=False|True`` parameter to start the
instance if even if secondary disks are failing.

It supports the ``dry-run`` argument.

``/2/instances/[instance_name]/reinstall``
++++++++++++++++++++++++++++++++++++++++++++++

Installs the operating system again.

It supports the following commands: ``POST``.

``POST``
~~~~~~~~

Takes the parameters ``os`` (OS template name) and ``nostartup`` (bool).


``/2/instances/[instance_name]/replace-disks``
++++++++++++++++++++++++++++++++++++++++++++++

Replaces disks on an instance.

It supports the following commands: ``POST``.

``POST``
~~~~~~~~

Takes the parameters ``mode`` (one of ``replace_on_primary``,
``replace_on_secondary``, ``replace_new_secondary`` or
``replace_auto``), ``disks`` (comma separated list of disk indexes),
``remote_node`` and ``iallocator``.


``/2/instances/[instance_name]/tags``
+++++++++++++++++++++++++++++++++++++

Manages per-instance tags.

It supports the following commands: ``GET``, ``PUT``, ``DELETE``.

``GET``
~~~~~~~

Returns a list of tags.

Example::

    ["tag1", "tag2", "tag3"]

``PUT``
~~~~~~~

Add a set of tags.

The request as a list of strings should be ``PUT`` to this URI. The
result will be a job id.

It supports the ``dry-run`` argument.


``DELETE``
~~~~~~~~~~

Delete a tag.

In order to delete a set of tags, the DELETE request should be addressed
to URI like::

    /tags?tag=[tag]&tag=[tag]

It supports the ``dry-run`` argument.


``/2/jobs``
+++++++++++

The ``/2/jobs`` resource.

It supports the following commands: ``GET``.

``GET``
~~~~~~~

Returns a dictionary of jobs.

Returns: a dictionary with jobs id and uri.

``/2/jobs/[job_id]``
++++++++++++++++++++


Individual job URI.

It supports the following commands: ``GET``, ``DELETE``.

``GET``
~~~~~~~

Returns a job status.

Returns: a dictionary with job parameters.

The result includes:

- id: job ID as a number
- status: current job status as a string
- ops: involved OpCodes as a list of dictionaries for each opcodes in
  the job
- opstatus: OpCodes status as a list
- opresult: OpCodes results as a list of lists

``DELETE``
~~~~~~~~~~

Cancel a not-yet-started job.

``/2/nodes``
++++++++++++

Nodes resource.

It supports the following commands: ``GET``.

``GET``
~~~~~~~

Returns a list of all nodes.

Example::

    [
      {
        "id": "node1.example.com",
        "uri": "\/instances\/node1.example.com"
      },
      {
        "id": "node2.example.com",
        "uri": "\/instances\/node2.example.com"
      }
    ]

If the optional 'bulk' argument is provided and set to 'true' value (i.e
'?bulk=1'), the output contains detailed information about nodes as a
list.

Example::

    [
      {
        "pinst_cnt": 1,
        "mfree": 31280,
        "mtotal": 32763,
        "name": "www.example.com",
        "tags": [],
        "mnode": 512,
        "dtotal": 5246208,
        "sinst_cnt": 2,
        "dfree": 5171712,
        "offline": false
      },
      ...
    ]

``/2/nodes/[node_name]``
+++++++++++++++++++++++++++++++++

Returns information about a node.

It supports the following commands: ``GET``.

``/2/nodes/[node_name]/evacuate``
+++++++++++++++++++++++++++++++++

Evacuates all secondary instances off a node.

It supports the following commands: ``POST``.

``POST``
~~~~~~~~

To evacuate a node, either one of the ``iallocator`` or ``remote_node``
parameters must be passed:

    evacuate?iallocator=[iallocator]
    evacuate?remote_node=[nodeX.example.com]

``/2/nodes/[node_name]/migrate``
+++++++++++++++++++++++++++++++++

Migrates all primary instances from a node.

It supports the following commands: ``POST``.

``POST``
~~~~~~~~

No parameters are required, but ``live`` can be set to a boolean value.

    migrate?live=[0|1]

``/2/nodes/[node_name]/role``
+++++++++++++++++++++++++++++

Manages node role.

It supports the following commands: ``GET``, ``PUT``.

The role is always one of the following:

  - drained
  - master
  - master-candidate
  - offline
  - regular

``GET``
~~~~~~~

Returns the current node role.

Example::

    "master-candidate"

``PUT``
~~~~~~~

Change the node role.

The request is a string which should be PUT to this URI. The result will
be a job id.

It supports the ``force`` argument.

``/2/nodes/[node_name]/storage``
++++++++++++++++++++++++++++++++

Manages storage units on the node.

``GET``
~~~~~~~

Requests a list of storage units on a node. Requires the parameters
``storage_type`` (one of ``file``, ``lvm-pv`` or ``lvm-vg``) and
``output_fields``. The result will be a job id, using which the result
can be retrieved.

``/2/nodes/[node_name]/storage/modify``
+++++++++++++++++++++++++++++++++++++++

Modifies storage units on the node.

``PUT``
~~~~~~~

Modifies parameters of storage units on the node. Requires the
parameters ``storage_type`` (one of ``file``, ``lvm-pv`` or ``lvm-vg``)
and ``name`` (name of the storage unit).  Parameters can be passed
additionally. Currently only ``allocatable`` (bool) is supported. The
result will be a job id.

``/2/nodes/[node_name]/storage/repair``
+++++++++++++++++++++++++++++++++++++++

Repairs a storage unit on the node.

``PUT``
~~~~~~~

Repairs a storage unit on the node. Requires the parameters
``storage_type`` (currently only ``lvm-vg`` can be repaired) and
``name`` (name of the storage unit). The result will be a job id.

``/2/nodes/[node_name]/tags``
+++++++++++++++++++++++++++++

Manages per-node tags.

It supports the following commands: ``GET``, ``PUT``, ``DELETE``.

``GET``
~~~~~~~

Returns a list of tags.

Example::

    ["tag1", "tag2", "tag3"]

``PUT``
~~~~~~~

Add a set of tags.

The request as a list of strings should be PUT to this URI. The result
will be a job id.

It supports the ``dry-run`` argument.

``DELETE``
~~~~~~~~~~

Deletes tags.

In order to delete a set of tags, the DELETE request should be addressed
to URI like::

    /tags?tag=[tag]&tag=[tag]

It supports the ``dry-run`` argument.


``/2/os``
+++++++++

OS resource.

It supports the following commands: ``GET``.

``GET``
~~~~~~~

Return a list of all OSes.

Can return error 500 in case of a problem. Since this is a costly
operation for Ganeti 2.0, it is not recommended to execute it too often.

Example::

    ["debian-etch"]

``/2/tags``
+++++++++++

Manages cluster tags.

It supports the following commands: ``GET``, ``PUT``, ``DELETE``.

``GET``
~~~~~~~

Returns the cluster tags.

Example::

    ["tag1", "tag2", "tag3"]

``PUT``
~~~~~~~

Adds a set of tags.

The request as a list of strings should be PUT to this URI. The result
will be a job id.

It supports the ``dry-run`` argument.


``DELETE``
~~~~~~~~~~

Deletes tags.

In order to delete a set of tags, the DELETE request should be addressed
to URI like::

    /tags?tag=[tag]&tag=[tag]

It supports the ``dry-run`` argument.


``/version``
++++++++++++

The version resource.

This resource should be used to determine the remote API version and to
adapt clients accordingly.

It supports the following commands: ``GET``.

``GET``
~~~~~~~

Returns the remote API version. Ganeti 1.2 returned ``1`` and Ganeti 2.0
returns ``2``.

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
