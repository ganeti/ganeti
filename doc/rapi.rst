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


Users and passwords
-------------------

``ganeti-rapi`` reads users and passwords from a file (usually
``/var/lib/ganeti/rapi_users``) on startup. After modifying the password
file, ``ganeti-rapi`` must be restarted.

Each line consists of two or three fields separated by whitespace. The
first two fields are for username and password. The third field is
optional and can be used to specify per-user options. Currently,
``write`` is the only option supported and enables the user to execute
operations modifying the cluster. Lines starting with the hash sign
(``#``) are treated as comments.

Passwords can either be written in clear text or as a hash. Clear text
passwords may not start with an opening brace (``{``) or they must be
prefixed with ``{cleartext}``. To use the hashed form, get the MD5 hash
of the string ``$username:Ganeti Remote API:$password`` (e.g. ``echo -n
'jack:Ganeti Remote API:abc123' | openssl md5``) [#pwhash]_ and prefix
it with ``{ha1}``. Using the scheme prefix for all passwords is
recommended. Scheme prefixes are not case sensitive.

Example::

  # Give Jack and Fred read-only access
  jack abc123
  fred {cleartext}foo555

  # Give write access to an imaginary instance creation script
  autocreator xyz789 write

  # Hashed password for Jessica
  jessica {HA1}7046452df2cbb530877058712cf17bd4 write


.. [#pwhash] Using the MD5 hash of username, realm and password is
   described in :rfc:`2617` ("HTTP Authentication"), sections 3.2.2.2 and
   3.3. The reason for using it over another algorithm is forward
   compatibility. If ``ganeti-rapi`` were to implement HTTP Digest
   authentication in the future, the same hash could be used.
   In the current version ``ganeti-rapi``'s realm, ``Ganeti Remote
   API``, can only be changed by modifying the source code.


Protocol
--------

The protocol used is JSON_ over HTTP designed after the REST_ principle.
HTTP Basic authentication as per :rfc:`2617` is supported.

.. _JSON: http://www.json.org/
.. _REST: http://en.wikipedia.org/wiki/Representational_State_Transfer


A note on JSON as used by RAPI
++++++++++++++++++++++++++++++

JSON_ as used by Ganeti RAPI does not conform to the specification in
:rfc:`4627`. Section 2 defines a JSON text to be either an object
(``{"key": "value", …}``) or an array (``[1, 2, 3, …]``). In violation
of this RAPI uses plain strings (``"master-candidate"``, ``"1234"``) for
some requests or responses. Changing this now would likely break
existing clients and cause a lot of trouble.

.. highlight:: ruby

Unlike Python's `JSON encoder and decoder
<http://docs.python.org/library/json.html>`_, other programming
languages or libraries may only provide a strict implementation, not
allowing plain values. For those, responses can usually be wrapped in an
array whose first element is then used, e.g. the response ``"1234"``
becomes ``["1234"]``. This works equally well for more complex values.
Example in Ruby::

  require "json"

  # Insert code to get response here
  response = "\"1234\""

  decoded = JSON.parse("[#{response}]").first

Short of modifying the encoder to allow encoding to a less strict
format, requests will have to be formatted by hand. Newer RAPI requests
already use a dictionary as their input data and shouldn't cause any
problems.


PUT or POST?
------------

According to :rfc:`2616` the main difference between PUT and POST is
that POST can create new resources but PUT can only create the resource
the URI was pointing to on the PUT request.

Unfortunately, due to historic reasons, the Ganeti RAPI library is not
consistent with this usage, so just use the methods as documented below
for each resource.

For more details have a look in the source code at
``lib/rapi/rlib2.py``.


Generic parameter types
-----------------------

A few generic refered parameter types and the values they allow.

``bool``
++++++++

A boolean option will accept ``1`` or ``0`` as numbers but not
i.e. ``True`` or ``False``.

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

The boolean *dry-run* argument, if provided and set, signals to Ganeti
that the job should not be executed, only the pre-execution checks will
be done.

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

Ganeti RAPI client
++++++++++++++++++

Ganeti includes a standalone RAPI client, ``lib/rapi/client.py``.

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


``/2/features``
+++++++++++++++

``GET``
~~~~~~~

Returns a list of features supported by the RAPI server. Available
features:

``instance-create-reqv1``
  Instance creation request data version 1 supported.


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

If the optional bool *bulk* argument is provided and set to a true value
(i.e ``?bulk=1``), the output contains detailed information about
instances as a list.

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

If the optional bool *dry-run* argument is provided, the job will not be
actually executed, only the pre-execution checks will be done. Query-ing
the job result will return, in both dry-run and normal case, the list of
nodes selected for the instance.

Returns: a job ID that can be used later for polling.

Body parameters:

``__version__`` (int, required)
  Must be ``1`` (older Ganeti versions used a different format for
  instance creation requests, version ``0``, but that format is not
  documented).
``mode`` (string, required)
  Instance creation mode.
``name`` (string, required)
  Instance name.
``disk_template`` (string, required)
  Disk template for instance.
``disks`` (list, required)
  List of disk definitions. Example: ``[{"size": 100}, {"size": 5}]``.
  Each disk definition must contain a ``size`` value and can contain an
  optional ``mode`` value denoting the disk access mode (``ro`` or
  ``rw``).
``nics`` (list, required)
  List of NIC (network interface) definitions. Example: ``[{}, {},
  {"ip": "198.51.100.4"}]``. Each NIC definition can contain the
  optional values ``ip``, ``mode``, ``link`` and ``bridge``.
``os`` (string, required)
  Instance operating system.
``osparams`` (dictionary)
  Dictionary with OS parameters. If not valid for the given OS, the job
  will fail.
``force_variant`` (bool)
  Whether to force an unknown variant.
``pnode`` (string)
  Primary node.
``snode`` (string)
  Secondary node.
``src_node`` (string)
  Source node for import.
``src_path`` (string)
  Source directory for import.
``start`` (bool)
  Whether to start instance after creation.
``ip_check`` (bool)
  Whether to ensure instance's IP address is inactive.
``name_check`` (bool)
  Whether to ensure instance's name is resolvable.
``file_storage_dir`` (string)
  File storage directory.
``file_driver`` (string)
  File storage driver.
``iallocator`` (string)
  Instance allocator name.
``source_handshake`` (list)
  Signed handshake from source (remote import only).
``source_x509_ca`` (string)
  Source X509 CA in PEM format (remote import only).
``source_instance_name`` (string)
  Source instance name (remote import only).
``hypervisor`` (string)
  Hypervisor name.
``hvparams`` (dict)
  Hypervisor parameters, hypervisor-dependent.
``beparams`` (dict)
  Backend parameters.


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

The URI takes optional ``type=soft|hard|full`` and
``ignore_secondaries=0|1`` parameters.

``type`` defines the reboot type. ``soft`` is just a normal reboot,
without terminating the hypervisor. ``hard`` means full shutdown
(including terminating the hypervisor process) and startup again.
``full`` is like ``hard`` but also recreates the configuration from
ground up as if you would have done a ``gnt-instance shutdown`` and
``gnt-instance start`` on it.

``ignore_secondaries`` is a bool argument indicating if we start the
instance even if secondary disks are failing.

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

The URI takes an optional ``force=1|0`` parameter to start the
instance even if secondary disks are failing.

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

Either ``remote_node`` or ``iallocator`` needs to be defined when using
``mode=replace_new_secondary``.

``mode`` is a mandatory parameter. ``replace_auto`` tries to determine
the broken disk(s) on its own and replacing it.


``/2/instances/[instance_name]/activate-disks``
+++++++++++++++++++++++++++++++++++++++++++++++

Activate disks on an instance.

It supports the following commands: ``PUT``.

``PUT``
~~~~~~~

Takes the bool parameter ``ignore_size``. When set ignore the recorded
size (useful for forcing activation when recorded size is wrong).


``/2/instances/[instance_name]/deactivate-disks``
+++++++++++++++++++++++++++++++++++++++++++++++++

Deactivate disks on an instance.

It supports the following commands: ``PUT``.

``PUT``
~~~~~~~

Takes no parameters.


``/2/instances/[instance_name]/prepare-export``
+++++++++++++++++++++++++++++++++++++++++++++++++

Prepares an export of an instance.

It supports the following commands: ``PUT``.

``PUT``
~~~~~~~

Takes one parameter, ``mode``, for the export mode. Returns a job ID.


``/2/instances/[instance_name]/export``
+++++++++++++++++++++++++++++++++++++++++++++++++

Exports an instance.

It supports the following commands: ``PUT``.

``PUT``
~~~~~~~

Returns a job ID.

Body parameters:

``mode`` (string)
  Export mode.
``destination`` (required)
  Destination information, depends on export mode.
``shutdown`` (bool, required)
  Whether to shutdown instance before export.
``remove_instance`` (bool)
  Whether to remove instance after export.
``x509_key_name``
  Name of X509 key (remote export only).
``destination_x509_ca``
  Destination X509 CA (remote export only).


``/2/instances/[instance_name]/migrate``
++++++++++++++++++++++++++++++++++++++++

Migrates an instance.

Supports the following commands: ``PUT``.

``PUT``
~~~~~~~

Returns a job ID.

Body parameters:

``mode`` (string)
  Migration mode.
``cleanup`` (bool)
  Whether a previously failed migration should be cleaned up.


``/2/instances/[instance_name]/rename``
++++++++++++++++++++++++++++++++++++++++

Renames an instance.

Supports the following commands: ``PUT``.

``PUT``
~~~~~~~

Returns a job ID.

Body parameters:

``new_name`` (string, required)
  New instance name.
``ip_check`` (bool)
  Whether to ensure instance's IP address is inactive.
``name_check`` (bool)
  Whether to ensure instance's name is resolvable.


``/2/instances/[instance_name]/modify``
++++++++++++++++++++++++++++++++++++++++

Modifies an instance.

Supports the following commands: ``PUT``.

``PUT``
~~~~~~~

Returns a job ID.

Body parameters:

``osparams`` (dict)
  Dictionary with OS parameters.
``hvparams`` (dict)
  Hypervisor parameters, hypervisor-dependent.
``beparams`` (dict)
  Backend parameters.
``force`` (bool)
  Whether to force the operation.
``nics`` (list)
  List of NIC changes. Each item is of the form ``(op, settings)``.
  ``op`` can be ``add`` to add a new NIC with the specified settings,
  ``remove`` to remove the last NIC or a number to modify the settings
  of the NIC with that index.
``disks`` (list)
  List of disk changes. See ``nics``.
``disk_template`` (string)
  Disk template for instance.
``remote_node`` (string)
  Secondary node (used when changing disk template).
``os_name`` (string)
  Change instance's OS name. Does not reinstall the instance.
``force_variant`` (bool)
  Whether to force an unknown variant.


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
- opresult: OpCodes results as a list

For a successful opcode, the ``opresult`` field corresponding to it will
contain the raw result from its :term:`LogicalUnit`. In case an opcode
has failed, its element in the opresult list will be a list of two
elements:

- first element the error type (the Ganeti internal error name)
- second element a list of either one or two elements:

  - the first element is the textual error description
  - the second element, if any, will hold an error classification

The error classification is most useful for the ``OpPrereqError``
error type - these errors happen before the OpCode has started
executing, so it's possible to retry the OpCode without side
effects. But whether it make sense to retry depends on the error
classification:

``resolver_error``
  Resolver errors. This usually means that a name doesn't exist in DNS,
  so if it's a case of slow DNS propagation the operation can be retried
  later.

``insufficient_resources``
  Not enough resources (iallocator failure, disk space, memory,
  etc.). If the resources on the cluster increase, the operation might
  succeed.

``wrong_input``
  Wrong arguments (at syntax level). The operation will not ever be
  accepted unless the arguments change.

``wrong_state``
  Wrong entity state. For example, live migration has been requested for
  a down instance, or instance creation on an offline node. The
  operation can be retried once the resource has changed state.

``unknown_entity``
  Entity not found. For example, information has been requested for an
  unknown instance.

``already_exists``
  Entity already exists. For example, instance creation has been
  requested for an already-existing instance.

``resource_not_unique``
  Resource not unique (e.g. MAC or IP duplication).

``internal_error``
  Internal cluster error. For example, a node is unreachable but not set
  offline, or the ganeti node daemons are not working, etc. A
  ``gnt-cluster verify`` should be run.

``environment_error``
  Environment error (e.g. node disk error). A ``gnt-cluster verify``
  should be run.

Note that in the above list, by entity we refer to a node or instance,
while by a resource we refer to an instance's disk, or NIC, etc.


``DELETE``
~~~~~~~~~~

Cancel a not-yet-started job.


``/2/jobs/[job_id]/wait``
+++++++++++++++++++++++++

``GET``
~~~~~~~

Waits for changes on a job. Takes the following body parameters in a
dict:

``fields``
  The job fields on which to watch for changes.

``previous_job_info``
  Previously received field values or None if not yet available.

``previous_log_serial``
  Highest log serial number received so far or None if not yet
  available.

Returns None if no changes have been detected and a dict with two keys,
``job_info`` and ``log_entries`` otherwise.


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
        "uri": "\/nodes\/node1.example.com"
      },
      {
        "id": "node2.example.com",
        "uri": "\/nodes\/node2.example.com"
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
parameters must be passed::

    evacuate?iallocator=[iallocator]
    evacuate?remote_node=[nodeX.example.com]

The result value will be a list, each element being a triple of the job
id (for this specific evacuation), the instance which is being evacuated
by this job, and the node to which it is being relocated. In case the
node is already empty, the result will be an empty list (without any
jobs being submitted).

And additional parameter ``early_release`` signifies whether to try to
parallelize the evacuations, at the risk of increasing I/O contention
and increasing the chances of data loss, if the primary node of any of
the instances being evacuated is not fully healthy.

If the dry-run parameter was specified, then the evacuation jobs were
not actually submitted, and the job IDs will be null.


``/2/nodes/[node_name]/migrate``
+++++++++++++++++++++++++++++++++

Migrates all primary instances from a node.

It supports the following commands: ``POST``.

``POST``
~~~~~~~~

If no mode is explicitly specified, each instances' hypervisor default
migration mode will be used. Query parameters:

``live`` (bool)
  If set, use live migration if available.
``mode`` (string)
  Sets migration mode, ``live`` for live migration and ``non-live`` for
  non-live migration. Supported by Ganeti 2.2 and above.


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

It supports the bool ``force`` argument.

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
