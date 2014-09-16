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

.. _rapi-users:

Users and passwords
-------------------

``ganeti-rapi`` reads users and passwords from a file (usually
``/var/lib/ganeti/rapi/users``) on startup. Changes to the file will be
read automatically.

Lines starting with the hash sign (``#``) are treated as comments. Each
line consists of two or three fields separated by whitespace. The first
two fields are for username and password. The third field is optional
and can be used to specify per-user options (separated by comma without
spaces).

Passwords can either be written in clear text or as a hash. Clear text
passwords may not start with an opening brace (``{``) or they must be
prefixed with ``{cleartext}``. To use the hashed form, get the MD5 hash
of the string ``$username:Ganeti Remote API:$password`` (e.g. ``echo -n
'jack:Ganeti Remote API:abc123' | openssl md5``) [#pwhash]_ and prefix
it with ``{ha1}``. Using the scheme prefix for all passwords is
recommended. Scheme prefixes are case insensitive.

Options control a user's access permissions. The section
:ref:`rapi-access-permissions` lists the permissions required for each
resource. If the ``--require-authentication`` command line option is
given to the ``ganeti-rapi`` daemon, all requests require
authentication. Available options:

.. pyassert::

  rapi.RAPI_ACCESS_ALL == set([
    rapi.RAPI_ACCESS_WRITE,
    rapi.RAPI_ACCESS_READ,
    ])

.. pyassert::

  rlib2.R_2_nodes_name_storage.GET_ACCESS == [rapi.RAPI_ACCESS_WRITE]

.. pyassert::

  rlib2.R_2_jobs_id_wait.GET_ACCESS == [rapi.RAPI_ACCESS_WRITE]

:pyeval:`rapi.RAPI_ACCESS_WRITE`
  Enables the user to execute operations modifying the cluster. Implies
  :pyeval:`rapi.RAPI_ACCESS_READ` access. Resources blocking other
  operations for read-only access, such as
  :ref:`/2/nodes/[node_name]/storage <rapi-res-nodes-node_name-storage+get>`
  or blocking server-side processes, such as
  :ref:`/2/jobs/[job_id]/wait <rapi-res-jobs-job_id-wait+get>`, use
  :pyeval:`rapi.RAPI_ACCESS_WRITE` to control access to their
  :pyeval:`http.HTTP_GET` method.
:pyeval:`rapi.RAPI_ACCESS_READ`
  Allow access to operations querying for information.

Example::

  # Give Jack and Fred read-only access
  jack abc123
  fred {cleartext}foo555

  # Give write access to an imaginary instance creation script
  autocreator xyz789 write

  # Hashed password for Jessica
  jessica {HA1}7046452df2cbb530877058712cf17bd4 write

  # Monitoring can query for values
  monitoring {HA1}ec018ffe72b8e75bb4d508ed5b6d079c read

  # A user who can read and write (the former is implied by granting
  # write access)
  superuser {HA1}ec018ffe72b8e75bb4d508ed5b6d079c read,write

When using the RAPI, username and password can be sent to the server
by using the standard HTTP basic access authentication. This means that
for accessing the protected URL ``https://cluster.example.com/resource``,
the address ``https://username:password@cluster.example.com/resource`` should
be used instead.
Alternatively, the appropriate parameter of your HTTP client
(such as ``-u`` for ``curl``) can be used.

.. [#pwhash] Using the MD5 hash of username, realm and password is
   described in :rfc:`2617` ("HTTP Authentication"), sections 3.2.2.2
   and 3.3. The reason for using it over another algorithm is forward
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

HTTP requests with a body (e.g. ``PUT`` or ``POST``) require the request
header ``Content-type`` be set to ``application/json`` (see :rfc:`2616`
(HTTP/1.1), section 7.2.1).


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

Parameter details
-----------------

Some parameters are not straight forward, so we describe them in details
here.

.. _rapi-ipolicy:

``ipolicy``
+++++++++++

The instance policy specification is a dict with the following fields:

.. pyassert::

  constants.IPOLICY_ALL_KEYS == set([constants.ISPECS_MINMAX,
                                     constants.ISPECS_STD,
                                     constants.IPOLICY_DTS,
                                     constants.IPOLICY_VCPU_RATIO,
                                     constants.IPOLICY_SPINDLE_RATIO])


.. pyassert::

  (set(constants.ISPECS_PARAMETER_TYPES.keys()) ==
   set([constants.ISPEC_MEM_SIZE,
        constants.ISPEC_DISK_SIZE,
        constants.ISPEC_DISK_COUNT,
        constants.ISPEC_CPU_COUNT,
        constants.ISPEC_NIC_COUNT,
        constants.ISPEC_SPINDLE_USE]))

.. |ispec-min| replace:: :pyeval:`constants.ISPECS_MIN`
.. |ispec-max| replace:: :pyeval:`constants.ISPECS_MAX`
.. |ispec-std| replace:: :pyeval:`constants.ISPECS_STD`


:pyeval:`constants.ISPECS_MINMAX`
  A list of dictionaries, each with the following two fields:

  |ispec-min|, |ispec-max|
    A sub- `dict` with the following fields, which sets the limit of the
    instances:

    :pyeval:`constants.ISPEC_MEM_SIZE`
      The size in MiB of the memory used
    :pyeval:`constants.ISPEC_DISK_SIZE`
      The size in MiB of the disk used
    :pyeval:`constants.ISPEC_DISK_COUNT`
      The numbers of disks used
    :pyeval:`constants.ISPEC_CPU_COUNT`
      The numbers of cpus used
    :pyeval:`constants.ISPEC_NIC_COUNT`
      The numbers of nics used
    :pyeval:`constants.ISPEC_SPINDLE_USE`
      The numbers of virtual disk spindles used by this instance. They
      are not real in the sense of actual HDD spindles, but useful for
      accounting the spindle usage on the residing node
|ispec-std|
  A sub- `dict` with the same fields as |ispec-min| and |ispec-max| above,
  which sets the standard values of the instances.
:pyeval:`constants.IPOLICY_DTS`
  A `list` of disk templates allowed for instances using this policy
:pyeval:`constants.IPOLICY_VCPU_RATIO`
  Maximum ratio of virtual to physical CPUs (`float`)
:pyeval:`constants.IPOLICY_SPINDLE_RATIO`
  Maximum ratio of instances to their node's ``spindle_count`` (`float`)

Usage examples
--------------

You can access the API using your favorite programming language as long
as it supports network connections.

Ganeti RAPI client
++++++++++++++++++

Ganeti includes a standalone RAPI client, ``lib/rapi/client.py``.

Shell
+++++

.. highlight:: shell-example

Using ``wget``::

   $ wget -q -O - https://%CLUSTERNAME%:5080/2/info

or ``curl``::

  $ curl https://%CLUSTERNAME%:5080/2/info

Note: with ``curl``, the request method (GET, POST, PUT) can be specified
using the ``-X`` command line option, and the username/password can be
specified with the ``-u`` option. In case of POST requests with a body, the
Content-Type can be set to JSON (as per the Protocol_ section) using the
parameter ``-H "Content-Type: application/json"``.

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

The root resource. Has no function, but for legacy reasons the ``GET``
method is supported.

``/2``
++++++

Has no function, but for legacy reasons the ``GET`` method is supported.

.. _rapi-res-info:

``/2/info``
+++++++++++

Cluster information resource.

.. rapi_resource_details:: /2/info


.. _rapi-res-info+get:

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
      },
    …
  }


.. _rapi-res-redistribute-config:

``/2/redistribute-config``
++++++++++++++++++++++++++

Redistribute configuration to all nodes.

.. rapi_resource_details:: /2/redistribute-config


.. _rapi-res-redistribute-config+put:

``PUT``
~~~~~~~

Redistribute configuration to all nodes. The result will be a job id.

Job result:

.. opcode_result:: OP_CLUSTER_REDIST_CONF


.. _rapi-res-features:

``/2/features``
+++++++++++++++

.. rapi_resource_details:: /2/features


.. _rapi-res-features+get:

``GET``
~~~~~~~

Returns a list of features supported by the RAPI server. Available
features:

.. pyassert::

  rlib2.ALL_FEATURES == set([rlib2._INST_CREATE_REQV1,
                             rlib2._INST_REINSTALL_REQV1,
                             rlib2._NODE_MIGRATE_REQV1,
                             rlib2._NODE_EVAC_RES1])

:pyeval:`rlib2._INST_CREATE_REQV1`
  Instance creation request data version 1 supported
:pyeval:`rlib2._INST_REINSTALL_REQV1`
  Instance reinstall supports body parameters
:pyeval:`rlib2._NODE_MIGRATE_REQV1`
  Whether migrating a node (``/2/nodes/[node_name]/migrate``) supports
  request body parameters
:pyeval:`rlib2._NODE_EVAC_RES1`
  Whether evacuating a node (``/2/nodes/[node_name]/evacuate``) returns
  a new-style result (see resource description)


.. _rapi-res-filters:

``/2/filters``
+++++++++++++++

The filters resource.

.. rapi_resource_details:: /2/filters


.. _rapi-res-filters+get:

``GET``
~~~~~~~

Returns a list of all existing filters.

Example::

    [
      {
        "id": "8b53f7de-f8e2-4470-99bd-1efe746e434f",
        "uri": "/2/filters/8b53f7de-f8e2-4470-99bd-1efe746e434f"
      },
      {
        "id": "b296f0c9-4809-46a8-b928-5ccf7720fa8c",
        "uri": "/2/filters/b296f0c9-4809-46a8-b928-5ccf7720fa8c"
      }
    ]

If the optional bool *bulk* argument is provided and set to a true value
(i.e ``?bulk=1``), the output contains detailed information about filters
as a list.

Returned fields: :pyeval:`utils.CommaJoin(sorted(rlib2.FILTER_RULE_FIELDS))`.

Example::

    [
      {
        "uuid": "8b53f7de-f8e2-4470-99bd-1efe746e434f",
        "watermark": 12534,
        "reason_trail": [
          ["luxid", "someFilterReason", 1409249801259897000]
        ],
        "priority": 0,
        "action": "REJECT",
        "predicates": [
          ["jobid", [">", "id", "watermark"]]
        ]
      },
      {
        "uuid": "b296f0c9-4809-46a8-b928-5ccf7720fa8c",
        "watermark": 12534,
        "reason_trail": [
          ["luxid", "someFilterReason", 1409249917268978000]
        ],
        "priority": 1,
        "action": "REJECT",
        "predicates": [
          ["opcode", ["=", "OP_ID", "OP_INSTANCE_CREATE"]]
        ]
      }
    ]


.. _rapi-res-filters+post:

``POST``
~~~~~~~~

Creates a filter.

Body parameters:

``priority`` (int, defaults to ``0``)
  Must be non-negative. Lower numbers mean higher filter priority.

``predicates`` (list, defaults to ``[]``)
  The first element is the name (``str``) of the predicate and the
  rest are parameters suitable for that predicate.
  Most predicates take a single parameter: A boolean expression
  in the Ganeti query language.

``action`` (defaults to ``"CONTINUE"``)
  The effect of the filter. Can be one of ``"ACCEPT"``, ``"PAUSE"``,
  ``"REJECT"``, ``"CONTINUE"`` and ``["RATE_LIMIT", n]``, where ``n``
  is a positive integer.

``reason`` (list, defaults to ``[]``)
  An initial reason trail for this filter. Each element in this list
  is a list with 3 elements: ``[source, reason, timestamp]``, where
  ``source`` and ``reason`` are strings and ``timestamp`` is a time
  since the UNIX epoch in nanoseconds as an integer.

Returns:

A filter UUID (``str``) that can be used for accessing the filter later.


.. _rapi-res-filters-filter_uuid:

``/2/filters/[filter_uuid]``
++++++++++++++++++++++++++++++

Returns information about a filter.

.. rapi_resource_details:: /2/filters/[filter_uuid]


.. _rapi-res-filters-filter_uuid+get:

``GET``
~~~~~~~

Returns information about a filter, similar to the bulk output from
the filter list.

Returned fields: :pyeval:`utils.CommaJoin(sorted(rlib2.FILTER_RULE_FIELDS))`.


.. _rapi-res-filters-filter_uuid+put:

``PUT``
~~~~~~~

Replaces a filter with given UUID, or creates it with the given UUID
if it doesn't already exist.

Body parameters:

All parameters for adding a new filter via ``POST``, plus the following:

``uuid``: (string)
  The UUID of the filter to replace or create.

Returns:

The filter UUID (``str``) of the replaced or created filter.
This will be the ``uuid`` body parameter if given, and a freshly generated
UUID otherwise.


.. _rapi-res-filters-filter_uuid+delete:

``DELETE``
~~~~~~~~~~

Deletes a filter.

Returns:

``None``


.. _rapi-res-modify:

``/2/modify``
++++++++++++++++++++++++++++++++++++++++

Modifies cluster parameters.

.. rapi_resource_details:: /2/modify


.. _rapi-res-modify+put:

``PUT``
~~~~~~~

Returns a job ID.

Body parameters:

.. opcode_params:: OP_CLUSTER_SET_PARAMS

Job result:

.. opcode_result:: OP_CLUSTER_SET_PARAMS


.. _rapi-res-groups:

``/2/groups``
+++++++++++++

The groups resource.

.. rapi_resource_details:: /2/groups


.. _rapi-res-groups+get:

``GET``
~~~~~~~

Returns a list of all existing node groups.

Example::

    [
      {
        "name": "group1",
        "uri": "\/2\/groups\/group1"
      },
      {
        "name": "group2",
        "uri": "\/2\/groups\/group2"
      }
    ]

If the optional bool *bulk* argument is provided and set to a true value
(i.e ``?bulk=1``), the output contains detailed information about node
groups as a list.

Returned fields: :pyeval:`utils.CommaJoin(sorted(rlib2.G_FIELDS))`.

Example::

    [
      {
        "name": "group1",
        "node_cnt": 2,
        "node_list": [
          "node1.example.com",
          "node2.example.com"
        ],
        "uuid": "0d7d407c-262e-49af-881a-6a430034bf43",
        …
      },
      {
        "name": "group2",
        "node_cnt": 1,
        "node_list": [
          "node3.example.com"
        ],
        "uuid": "f5a277e7-68f9-44d3-a378-4b25ecb5df5c",
        …
      },
      …
    ]


.. _rapi-res-groups+post:

``POST``
~~~~~~~~

Creates a node group.

If the optional bool *dry-run* argument is provided, the job will not be
actually executed, only the pre-execution checks will be done.

Returns: a job ID that can be used later for polling.

Body parameters:

.. opcode_params:: OP_GROUP_ADD

Earlier versions used a parameter named ``name`` which, while still
supported, has been renamed to ``group_name``.

Job result:

.. opcode_result:: OP_GROUP_ADD


.. _rapi-res-groups-group_name:

``/2/groups/[group_name]``
++++++++++++++++++++++++++

Returns information about a node group.

.. rapi_resource_details:: /2/groups/[group_name]


.. _rapi-res-groups-group_name+get:

``GET``
~~~~~~~

Returns information about a node group, similar to the bulk output from
the node group list.

Returned fields: :pyeval:`utils.CommaJoin(sorted(rlib2.G_FIELDS))`.

.. _rapi-res-groups-group_name+delete:

``DELETE``
~~~~~~~~~~

Deletes a node group.

It supports the ``dry-run`` argument.

Job result:

.. opcode_result:: OP_GROUP_REMOVE


.. _rapi-res-groups-group_name-modify:

``/2/groups/[group_name]/modify``
+++++++++++++++++++++++++++++++++

Modifies the parameters of a node group.

.. rapi_resource_details:: /2/groups/[group_name]/modify


.. _rapi-res-groups-group_name-modify+put:

``PUT``
~~~~~~~

Returns a job ID.

Body parameters:

.. opcode_params:: OP_GROUP_SET_PARAMS
   :exclude: group_name

Job result:

.. opcode_result:: OP_GROUP_SET_PARAMS


.. _rapi-res-groups-group_name-rename:

``/2/groups/[group_name]/rename``
+++++++++++++++++++++++++++++++++

Renames a node group.

.. rapi_resource_details:: /2/groups/[group_name]/rename


.. _rapi-res-groups-group_name-rename+put:

``PUT``
~~~~~~~

Returns a job ID.

Body parameters:

.. opcode_params:: OP_GROUP_RENAME
   :exclude: group_name

Job result:

.. opcode_result:: OP_GROUP_RENAME


.. _rapi-res-groups-group_name-assign-nodes:

``/2/groups/[group_name]/assign-nodes``
+++++++++++++++++++++++++++++++++++++++

Assigns nodes to a group.

.. rapi_resource_details:: /2/groups/[group_name]/assign-nodes

.. _rapi-res-groups-group_name-assign-nodes+put:

``PUT``
~~~~~~~

Returns a job ID. It supports the ``dry-run`` and ``force`` arguments.

Body parameters:

.. opcode_params:: OP_GROUP_ASSIGN_NODES
   :exclude: group_name, force, dry_run

Job result:

.. opcode_result:: OP_GROUP_ASSIGN_NODES

.. _rapi-res-groups-group_name-tags:

``/2/groups/[group_name]/tags``
+++++++++++++++++++++++++++++++

Manages per-nodegroup tags.

.. rapi_resource_details:: /2/groups/[group_name]/tags


.. _rapi-res-groups-group_name-tags+get:

``GET``
~~~~~~~

Returns a list of tags.

Example::

    ["tag1", "tag2", "tag3"]

.. _rapi-res-groups-group_name-tags+put:

``PUT``
~~~~~~~

Add a set of tags.

The request as a list of strings should be ``PUT`` to this URI. The
result will be a job id.

It supports the ``dry-run`` argument.


.. _rapi-res-groups-group_name-tags+delete:

``DELETE``
~~~~~~~~~~

Delete a tag.

In order to delete a set of tags, the DELETE request should be addressed
to URI like::

    /tags?tag=[tag]&tag=[tag]

It supports the ``dry-run`` argument.


.. _rapi-res-networks:

``/2/networks``
+++++++++++++++

The networks resource.

.. rapi_resource_details:: /2/networks


.. _rapi-res-networks+get:

``GET``
~~~~~~~

Returns a list of all existing networks.

Example::

    [
      {
        "name": "network1",
        "uri": "\/2\/networks\/network1"
      },
      {
        "name": "network2",
        "uri": "\/2\/networks\/network2"
      }
    ]

If the optional bool *bulk* argument is provided and set to a true value
(i.e ``?bulk=1``), the output contains detailed information about networks
as a list.

Returned fields: :pyeval:`utils.CommaJoin(sorted(rlib2.NET_FIELDS))`.

Example::

    [
      {
        'external_reservations': '10.0.0.0, 10.0.0.1, 10.0.0.15',
        'free_count': 13,
        'gateway': '10.0.0.1',
        'gateway6': None,
        'group_list': ['default(bridged, prv0)'],
        'inst_list': [],
        'mac_prefix': None,
        'map': 'XX.............X',
        'name': 'nat',
        'network': '10.0.0.0/28',
        'network6': None,
        'reserved_count': 3,
        'tags': ['nfdhcpd'],
        …
      },
      …
    ]


.. _rapi-res-networks+post:

``POST``
~~~~~~~~

Creates a network.

If the optional bool *dry-run* argument is provided, the job will not be
actually executed, only the pre-execution checks will be done.

Returns: a job ID that can be used later for polling.

Body parameters:

.. opcode_params:: OP_NETWORK_ADD

Job result:

.. opcode_result:: OP_NETWORK_ADD


.. _rapi-res-networks-network_name:

``/2/networks/[network_name]``
++++++++++++++++++++++++++++++

Returns information about a network.

.. rapi_resource_details:: /2/networks/[network_name]


.. _rapi-res-networks-network_name+get:

``GET``
~~~~~~~

Returns information about a network, similar to the bulk output from
the network list.

Returned fields: :pyeval:`utils.CommaJoin(sorted(rlib2.NET_FIELDS))`.


.. _rapi-res-networks-network_name+delete:

``DELETE``
~~~~~~~~~~

Deletes a network.

It supports the ``dry-run`` argument.

Job result:

.. opcode_result:: OP_NETWORK_REMOVE


.. _rapi-res-networks-network_name-modify:

``/2/networks/[network_name]/modify``
+++++++++++++++++++++++++++++++++++++

Modifies the parameters of a network.

.. rapi_resource_details:: /2/networks/[network_name]/modify


.. _rapi-res-networks-network_name-modify+put:

``PUT``
~~~~~~~

Returns a job ID.

Body parameters:

.. opcode_params:: OP_NETWORK_SET_PARAMS

Job result:

.. opcode_result:: OP_NETWORK_SET_PARAMS


.. _rapi-res-networks-network_name-connect:

``/2/networks/[network_name]/connect``
++++++++++++++++++++++++++++++++++++++

Connects a network to a nodegroup.

.. rapi_resource_details:: /2/networks/[network_name]/connect


.. _rapi-res-networks-network_name-connect+put:

``PUT``
~~~~~~~

Returns a job ID. It supports the ``dry-run`` arguments.

Body parameters:

.. opcode_params:: OP_NETWORK_CONNECT

Job result:

.. opcode_result:: OP_NETWORK_CONNECT


.. _rapi-res-networks-network_name-disconnect:

``/2/networks/[network_name]/disconnect``
+++++++++++++++++++++++++++++++++++++++++

Disonnects a network from a nodegroup.

.. rapi_resource_details:: /2/networks/[network_name]/disconnect


.. _rapi-res-networks-network_name-disconnect+put:

``PUT``
~~~~~~~

Returns a job ID. It supports the ``dry-run`` arguments.

Body parameters:

.. opcode_params:: OP_NETWORK_DISCONNECT

Job result:

.. opcode_result:: OP_NETWORK_DISCONNECT


.. _rapi-res-networks-network_name-tags:

``/2/networks/[network_name]/tags``
+++++++++++++++++++++++++++++++++++

Manages per-network tags.

.. rapi_resource_details:: /2/networks/[network_name]/tags


.. _rapi-res-networks-network_name-tags+get:

``GET``
~~~~~~~

Returns a list of tags.

Example::

    ["tag1", "tag2", "tag3"]


.. _rapi-res-networks-network_name-tags+put:

``PUT``
~~~~~~~

Add a set of tags.

The request as a list of strings should be ``PUT`` to this URI. The
result will be a job id.

It supports the ``dry-run`` argument.


.. _rapi-res-networks-network_name-tags+delete:

``DELETE``
~~~~~~~~~~

Delete a tag.

In order to delete a set of tags, the DELETE request should be addressed
to URI like::

    /tags?tag=[tag]&tag=[tag]

It supports the ``dry-run`` argument.


.. _rapi-res-instances-multi-alloc:

``/2/instances-multi-alloc``
++++++++++++++++++++++++++++

Tries to allocate multiple instances.

.. rapi_resource_details:: /2/instances-multi-alloc


.. _rapi-res-instances-multi-alloc+post:

``POST``
~~~~~~~~

The parameters:

.. opcode_params:: OP_INSTANCE_MULTI_ALLOC

Job result:

.. opcode_result:: OP_INSTANCE_MULTI_ALLOC


.. _rapi-res-instances:

``/2/instances``
++++++++++++++++

The instances resource.

.. rapi_resource_details:: /2/instances


.. _rapi-res-instances+get:

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

Returned fields: :pyeval:`utils.CommaJoin(sorted(rlib2.I_FIELDS))`.

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
        "oper_state": true,
        …
      },
      …
    ]


.. _rapi-res-instances+post:

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
  instance creation requests, version ``0``, but that format is no
  longer supported)

.. opcode_params:: OP_INSTANCE_CREATE

Earlier versions used parameters named ``name`` and ``os``. These have
been replaced by ``instance_name`` and ``os_type`` to match the
underlying opcode. The old names can still be used.

Job result:

.. opcode_result:: OP_INSTANCE_CREATE


.. _rapi-res-instances-instance_name:

``/2/instances/[instance_name]``
++++++++++++++++++++++++++++++++

Instance-specific resource.

.. rapi_resource_details:: /2/instances/[instance_name]


.. _rapi-res-instances-instance_name+get:

``GET``
~~~~~~~

Returns information about an instance, similar to the bulk output from
the instance list.

Returned fields: :pyeval:`utils.CommaJoin(sorted(rlib2.I_FIELDS))`.


.. _rapi-res-instances-instance_name+delete:

``DELETE``
~~~~~~~~~~

Deletes an instance.

It supports the ``dry-run`` argument.

Job result:

.. opcode_result:: OP_INSTANCE_REMOVE


.. _rapi-res-instances-instance_name-info:

``/2/instances/[instance_name]/info``
+++++++++++++++++++++++++++++++++++++++

.. rapi_resource_details:: /2/instances/[instance_name]/info


.. _rapi-res-instances-instance_name-info+get:

``GET``
~~~~~~~

Requests detailed information about the instance. An optional parameter,
``static`` (bool), can be set to return only static information from the
configuration without querying the instance's nodes. The result will be
a job id.

Job result:

.. opcode_result:: OP_INSTANCE_QUERY_DATA


.. _rapi-res-instances-instance_name-reboot:

``/2/instances/[instance_name]/reboot``
+++++++++++++++++++++++++++++++++++++++

Reboots URI for an instance.

.. rapi_resource_details:: /2/instances/[instance_name]/reboot


.. _rapi-res-instances-instance_name-reboot+post:

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

Job result:

.. opcode_result:: OP_INSTANCE_REBOOT


.. _rapi-res-instances-instance_name-shutdown:

``/2/instances/[instance_name]/shutdown``
+++++++++++++++++++++++++++++++++++++++++

Instance shutdown URI.

.. rapi_resource_details:: /2/instances/[instance_name]/shutdown


.. _rapi-res-instances-instance_name-shutdown+put:

``PUT``
~~~~~~~

Shutdowns an instance.

It supports the ``dry-run`` argument.

.. opcode_params:: OP_INSTANCE_SHUTDOWN
   :exclude: instance_name, dry_run

Job result:

.. opcode_result:: OP_INSTANCE_SHUTDOWN


.. _rapi-res-instances-instance_name-startup:

``/2/instances/[instance_name]/startup``
++++++++++++++++++++++++++++++++++++++++

Instance startup URI.

.. rapi_resource_details:: /2/instances/[instance_name]/startup


.. _rapi-res-instances-instance_name-startup+put:

``PUT``
~~~~~~~

Startup an instance.

The URI takes an optional ``force=1|0`` parameter to start the
instance even if secondary disks are failing.

It supports the ``dry-run`` argument.

Job result:

.. opcode_result:: OP_INSTANCE_STARTUP


.. _rapi-res-instances-instance_name-reinstall:

``/2/instances/[instance_name]/reinstall``
++++++++++++++++++++++++++++++++++++++++++++++

Installs the operating system again.

.. rapi_resource_details:: /2/instances/[instance_name]/reinstall


.. _rapi-res-instances-instance_name-reinstall+post:

``POST``
~~~~~~~~

Returns a job ID.

Body parameters:

``os`` (string, required)
  Instance operating system.
``start`` (bool, defaults to true)
  Whether to start instance after reinstallation.
``osparams`` (dict)
  Dictionary with (temporary) OS parameters.

For backwards compatbility, this resource also takes the query
parameters ``os`` (OS template name) and ``nostartup`` (bool). New
clients should use the body parameters.


.. _rapi-res-instances-instance_name-replace-disks:

``/2/instances/[instance_name]/replace-disks``
++++++++++++++++++++++++++++++++++++++++++++++

Replaces disks on an instance.

.. rapi_resource_details:: /2/instances/[instance_name]/replace-disks


.. _rapi-res-instances-instance_name-replace-disks+post:

``POST``
~~~~~~~~

Returns a job ID.

Body parameters:

.. opcode_params:: OP_INSTANCE_REPLACE_DISKS
   :exclude: instance_name

Ganeti 2.4 and below used query parameters. Those are deprecated and
should no longer be used.

Job result:

.. opcode_result:: OP_INSTANCE_REPLACE_DISKS


.. _rapi-res-instances-instance_name-activate-disks:

``/2/instances/[instance_name]/activate-disks``
+++++++++++++++++++++++++++++++++++++++++++++++

Activate disks on an instance.

.. rapi_resource_details:: /2/instances/[instance_name]/activate-disks


.. _rapi-res-instances-instance_name-activate-disks+put:

``PUT``
~~~~~~~

Takes the bool parameter ``ignore_size``. When set ignore the recorded
size (useful for forcing activation when recorded size is wrong).

Job result:

.. opcode_result:: OP_INSTANCE_ACTIVATE_DISKS


.. _rapi-res-instances-instance_name-deactivate-disks:

``/2/instances/[instance_name]/deactivate-disks``
+++++++++++++++++++++++++++++++++++++++++++++++++

Deactivate disks on an instance.

.. rapi_resource_details:: /2/instances/[instance_name]/deactivate-disks


.. _rapi-res-instances-instance_name-deactivate-disks+put:

``PUT``
~~~~~~~

Takes no parameters.

Job result:

.. opcode_result:: OP_INSTANCE_DEACTIVATE_DISKS


.. _rapi-res-instances-instance_name-recreate-disks:

``/2/instances/[instance_name]/recreate-disks``
+++++++++++++++++++++++++++++++++++++++++++++++++

Recreate disks of an instance.

.. rapi_resource_details:: /2/instances/[instance_name]/recreate-disks


.. _rapi-res-instances-instance_name-recreate-disks+post:

``POST``
~~~~~~~~

Returns a job ID.

Body parameters:

.. opcode_params:: OP_INSTANCE_RECREATE_DISKS
   :exclude: instance_name

Job result:

.. opcode_result:: OP_INSTANCE_RECREATE_DISKS


.. _rapi-res-instances-instance_name-disk-disk_index-grow:

``/2/instances/[instance_name]/disk/[disk_index]/grow``
+++++++++++++++++++++++++++++++++++++++++++++++++++++++

Grows one disk of an instance.

.. rapi_resource_details:: /2/instances/[instance_name]/disk/[disk_index]/grow


.. _rapi-res-instances-instance_name-disk-disk_index-grow+post:

``POST``
~~~~~~~~

Returns a job ID.

Body parameters:

.. opcode_params:: OP_INSTANCE_GROW_DISK
   :exclude: instance_name, disk

Job result:

.. opcode_result:: OP_INSTANCE_GROW_DISK


.. _rapi-res-instances-instance_name-prepare-export:

``/2/instances/[instance_name]/prepare-export``
+++++++++++++++++++++++++++++++++++++++++++++++++

Prepares an export of an instance.

.. rapi_resource_details:: /2/instances/[instance_name]/prepare-export


.. _rapi-res-instances-instance_name-prepare-export+put:

``PUT``
~~~~~~~

Takes one parameter, ``mode``, for the export mode. Returns a job ID.

Job result:

.. opcode_result:: OP_BACKUP_PREPARE


.. _rapi-res-instances-instance_name-export:

``/2/instances/[instance_name]/export``
+++++++++++++++++++++++++++++++++++++++++++++++++

Exports an instance.

.. rapi_resource_details:: /2/instances/[instance_name]/export


.. _rapi-res-instances-instance_name-export+put:

``PUT``
~~~~~~~

Returns a job ID.

Body parameters:

.. opcode_params:: OP_BACKUP_EXPORT
   :exclude: instance_name
   :alias: target_node=destination

Job result:

.. opcode_result:: OP_BACKUP_EXPORT


.. _rapi-res-instances-instance_name-migrate:

``/2/instances/[instance_name]/migrate``
++++++++++++++++++++++++++++++++++++++++

Migrates an instance.

.. rapi_resource_details:: /2/instances/[instance_name]/migrate


.. _rapi-res-instances-instance_name-migrate+put:

``PUT``
~~~~~~~

Returns a job ID.

Body parameters:

.. opcode_params:: OP_INSTANCE_MIGRATE
   :exclude: instance_name, live

Job result:

.. opcode_result:: OP_INSTANCE_MIGRATE


.. _rapi-res-instances-instance_name-failover:

``/2/instances/[instance_name]/failover``
+++++++++++++++++++++++++++++++++++++++++

Does a failover of an instance.

.. rapi_resource_details:: /2/instances/[instance_name]/failover


.. _rapi-res-instances-instance_name-failover+put:

``PUT``
~~~~~~~

Returns a job ID.

Body parameters:

.. opcode_params:: OP_INSTANCE_FAILOVER
   :exclude: instance_name

Job result:

.. opcode_result:: OP_INSTANCE_FAILOVER


.. _rapi-res-instances-instance_name-rename:

``/2/instances/[instance_name]/rename``
++++++++++++++++++++++++++++++++++++++++

Renames an instance.

.. rapi_resource_details:: /2/instances/[instance_name]/rename


.. _rapi-res-instances-instance_name-rename+put:

``PUT``
~~~~~~~

Returns a job ID.

Body parameters:

.. opcode_params:: OP_INSTANCE_RENAME
   :exclude: instance_name

Job result:

.. opcode_result:: OP_INSTANCE_RENAME


.. _rapi-res-instances-instance_name-modify:

``/2/instances/[instance_name]/modify``
++++++++++++++++++++++++++++++++++++++++

Modifies an instance.

.. rapi_resource_details:: /2/instances/[instance_name]/modify


.. _rapi-res-instances-instance_name-modify+put:

``PUT``
~~~~~~~

Returns a job ID.

Body parameters:

.. opcode_params:: OP_INSTANCE_SET_PARAMS
   :exclude: instance_name

Job result:

.. opcode_result:: OP_INSTANCE_SET_PARAMS


.. _rapi-res-instances-instance_name-console:

``/2/instances/[instance_name]/console``
++++++++++++++++++++++++++++++++++++++++

Request information for connecting to instance's console.

.. rapi_resource_details:: /2/instances/[instance_name]/console


.. _rapi-res-instances-instance_name-console+get:

``GET``
~~~~~~~

Returns a dictionary containing information about the instance's
console. Contained keys:

.. pyassert::

   constants.CONS_ALL == frozenset([
     constants.CONS_MESSAGE,
     constants.CONS_SSH,
     constants.CONS_VNC,
     constants.CONS_SPICE,
     ])

.. pyassert::

  frozenset(objects.InstanceConsole.GetAllSlots()) == frozenset([
    "command",
    "display",
    "host",
    "instance",
    "kind",
    "message",
    "port",
    "user",
    ])


``instance``
  Instance name
``kind``
  Console type, one of :pyeval:`constants.CONS_SSH`,
  :pyeval:`constants.CONS_VNC`, :pyeval:`constants.CONS_SPICE`
  or :pyeval:`constants.CONS_MESSAGE`
``message``
  Message to display (:pyeval:`constants.CONS_MESSAGE` type only)
``host``
  Host to connect to (:pyeval:`constants.CONS_SSH`,
  :pyeval:`constants.CONS_VNC` or :pyeval:`constants.CONS_SPICE` only)
``port``
  TCP port to connect to (:pyeval:`constants.CONS_VNC` or
  :pyeval:`constants.CONS_SPICE` only)
``user``
  Username to use (:pyeval:`constants.CONS_SSH` only)
``command``
  Command to execute on machine (:pyeval:`constants.CONS_SSH` only)
``display``
  VNC display number (:pyeval:`constants.CONS_VNC` only)


.. _rapi-res-instances-instance_name-tags:

``/2/instances/[instance_name]/tags``
+++++++++++++++++++++++++++++++++++++

Manages per-instance tags.

.. rapi_resource_details:: /2/instances/[instance_name]/tags


.. _rapi-res-instances-instance_name-tags+get:

``GET``
~~~~~~~

Returns a list of tags.

Example::

    ["tag1", "tag2", "tag3"]


.. _rapi-res-instances-instance_name-tags+put:

``PUT``
~~~~~~~

Add a set of tags.

The request as a list of strings should be ``PUT`` to this URI. The
result will be a job id.

It supports the ``dry-run`` argument.


.. _rapi-res-instances-instance_name-tags+delete:

``DELETE``
~~~~~~~~~~

Delete a tag.

In order to delete a set of tags, the DELETE request should be addressed
to URI like::

    /tags?tag=[tag]&tag=[tag]

It supports the ``dry-run`` argument.


.. _rapi-res-jobs:

``/2/jobs``
+++++++++++

The ``/2/jobs`` resource.

.. rapi_resource_details:: /2/jobs


.. _rapi-res-jobs+get:

``GET``
~~~~~~~

Returns a dictionary of jobs.

Returns: a dictionary with jobs id and uri.

If the optional bool *bulk* argument is provided and set to a true value
(i.e. ``?bulk=1``), the output contains detailed information about jobs
as a list.

Returned fields for bulk requests (unlike other bulk requests, these
fields are not the same as for per-job requests):
:pyeval:`utils.CommaJoin(sorted(rlib2.J_FIELDS_BULK))`.


.. _rapi-res-jobs-job_id:

``/2/jobs/[job_id]``
++++++++++++++++++++

Individual job URI.

.. rapi_resource_details:: /2/jobs/[job_id]


.. _rapi-res-jobs-job_id+get:

``GET``
~~~~~~~

Returns a dictionary with job parameters, containing the fields
:pyeval:`utils.CommaJoin(sorted(rlib2.J_FIELDS))`.

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

.. pyassert::

   errors.ECODE_ALL == set([errors.ECODE_RESOLVER, errors.ECODE_NORES,
     errors.ECODE_INVAL, errors.ECODE_STATE, errors.ECODE_NOENT,
     errors.ECODE_EXISTS, errors.ECODE_NOTUNIQUE, errors.ECODE_FAULT,
     errors.ECODE_ENVIRON, errors.ECODE_TEMP_NORES])

:pyeval:`errors.ECODE_RESOLVER`
  Resolver errors. This usually means that a name doesn't exist in DNS,
  so if it's a case of slow DNS propagation the operation can be retried
  later.

:pyeval:`errors.ECODE_NORES`
  Not enough resources (iallocator failure, disk space, memory,
  etc.). If the resources on the cluster increase, the operation might
  succeed.

:pyeval:`errors.ECODE_TEMP_NORES`
  Simliar to :pyeval:`errors.ECODE_NORES`, but indicating the operation
  should be attempted again after some time.

:pyeval:`errors.ECODE_INVAL`
  Wrong arguments (at syntax level). The operation will not ever be
  accepted unless the arguments change.

:pyeval:`errors.ECODE_STATE`
  Wrong entity state. For example, live migration has been requested for
  a down instance, or instance creation on an offline node. The
  operation can be retried once the resource has changed state.

:pyeval:`errors.ECODE_NOENT`
  Entity not found. For example, information has been requested for an
  unknown instance.

:pyeval:`errors.ECODE_EXISTS`
  Entity already exists. For example, instance creation has been
  requested for an already-existing instance.

:pyeval:`errors.ECODE_NOTUNIQUE`
  Resource not unique (e.g. MAC or IP duplication).

:pyeval:`errors.ECODE_FAULT`
  Internal cluster error. For example, a node is unreachable but not set
  offline, or the ganeti node daemons are not working, etc. A
  ``gnt-cluster verify`` should be run.

:pyeval:`errors.ECODE_ENVIRON`
  Environment error (e.g. node disk error). A ``gnt-cluster verify``
  should be run.

Note that in the above list, by entity we refer to a node or instance,
while by a resource we refer to an instance's disk, or NIC, etc.


.. _rapi-res-jobs-job_id+delete:

``DELETE``
~~~~~~~~~~

Cancel a not-yet-started job.


.. _rapi-res-jobs-job_id-wait:

``/2/jobs/[job_id]/wait``
+++++++++++++++++++++++++

.. rapi_resource_details:: /2/jobs/[job_id]/wait


.. _rapi-res-jobs-job_id-wait+get:

``GET``
~~~~~~~

Waits for changes on a job. Takes the following body parameters in a
dict:

``fields``
  The job fields on which to watch for changes

``previous_job_info``
  Previously received field values or None if not yet available

``previous_log_serial``
  Highest log serial number received so far or None if not yet
  available

Returns None if no changes have been detected and a dict with two keys,
``job_info`` and ``log_entries`` otherwise.


.. _rapi-res-nodes:

``/2/nodes``
++++++++++++

Nodes resource.

.. rapi_resource_details:: /2/nodes


.. _rapi-res-nodes+get:

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

If the optional bool *bulk* argument is provided and set to a true value
(i.e ``?bulk=1``), the output contains detailed information about nodes
as a list.

Returned fields: :pyeval:`utils.CommaJoin(sorted(rlib2.N_FIELDS))`.

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
        "offline": false,
        …
      },
      …
    ]


.. _rapi-res-nodes-node_name:

``/2/nodes/[node_name]``
+++++++++++++++++++++++++++++++++

Returns information about a node.

.. rapi_resource_details:: /2/nodes/[node_name]


.. _rapi-res-nodes-node_name+get:

``GET``
~~~~~~~

Returned fields: :pyeval:`utils.CommaJoin(sorted(rlib2.N_FIELDS))`.



.. _rapi-res-nodes-node_name-powercycle:

``/2/nodes/[node_name]/powercycle``
+++++++++++++++++++++++++++++++++++

Powercycles a node.

.. rapi_resource_details:: /2/nodes/[node_name]/powercycle


.. _rapi-res-nodes-node_name-powercycle+post:

``POST``
~~~~~~~~

Returns a job ID.

Job result:

.. opcode_result:: OP_NODE_POWERCYCLE


.. _rapi-res-nodes-node_name-evacuate:

``/2/nodes/[node_name]/evacuate``
+++++++++++++++++++++++++++++++++

Evacuates instances off a node.

.. rapi_resource_details:: /2/nodes/[node_name]/evacuate


.. _rapi-res-nodes-node_name-evacuate+post:

``POST``
~~~~~~~~

Returns a job ID. The result of the job will contain the IDs of the
individual jobs submitted to evacuate the node.

Body parameters:

.. opcode_params:: OP_NODE_EVACUATE
   :exclude: nodes

Up to and including Ganeti 2.4 query arguments were used. Those are no
longer supported. The new request can be detected by the presence of the
:pyeval:`rlib2._NODE_EVAC_RES1` feature string.

Job result:

.. opcode_result:: OP_NODE_EVACUATE


.. _rapi-res-nodes-node_name-migrate:

``/2/nodes/[node_name]/migrate``
+++++++++++++++++++++++++++++++++

Migrates all primary instances from a node.

.. rapi_resource_details:: /2/nodes/[node_name]/migrate


.. _rapi-res-nodes-node_name-migrate+post:

``POST``
~~~~~~~~

If no mode is explicitly specified, each instances' hypervisor default
migration mode will be used. Body parameters:

.. opcode_params:: OP_NODE_MIGRATE
   :exclude: node_name

The query arguments used up to and including Ganeti 2.4 are deprecated
and should no longer be used. The new request format can be detected by
the presence of the :pyeval:`rlib2._NODE_MIGRATE_REQV1` feature string.

Job result:

.. opcode_result:: OP_NODE_MIGRATE


.. _rapi-res-nodes-node_name-role:

``/2/nodes/[node_name]/role``
+++++++++++++++++++++++++++++

Manages node role.

.. rapi_resource_details:: /2/nodes/[node_name]/role

The role is always one of the following:

  - drained
  - master-candidate
  - offline
  - regular

Note that the 'master' role is a special, and currently it can't be
modified via RAPI, only via the command line (``gnt-cluster
master-failover``).


.. _rapi-res-nodes-node_name-role+get:

``GET``
~~~~~~~

Returns the current node role.

Example::

    "master-candidate"


.. _rapi-res-nodes-node_name-role+put:

``PUT``
~~~~~~~

Change the node role.

The request is a string which should be PUT to this URI. The result will
be a job id.

It supports the bool ``force`` argument.

Job result:

.. opcode_result:: OP_NODE_SET_PARAMS


.. _rapi-res-nodes-node_name-modify:

``/2/nodes/[node_name]/modify``
+++++++++++++++++++++++++++++++

Modifies the parameters of a node.

.. rapi_resource_details:: /2/nodes/[node_name]/modify


.. _rapi-res-nodes-node_name-modify+post:

``POST``
~~~~~~~~

Returns a job ID.

Body parameters:

.. opcode_params:: OP_NODE_SET_PARAMS
   :exclude: node_name

Job result:

.. opcode_result:: OP_NODE_SET_PARAMS


.. _rapi-res-nodes-node_name-storage:

``/2/nodes/[node_name]/storage``
++++++++++++++++++++++++++++++++

Manages storage units on the node.

.. rapi_resource_details:: /2/nodes/[node_name]/storage


.. _rapi-res-nodes-node_name-storage+get:

``GET``
~~~~~~~

.. pyassert::

   constants.STS_REPORT == set([constants.ST_FILE,
                                constants.ST_LVM_PV,
                                constants.ST_LVM_VG])

Requests a list of storage units on a node. Requires the parameters
``storage_type`` for storage types that support space reporting
(one of :pyeval:`constants.ST_FILE`, :pyeval:`constants.ST_LVM_PV`
or :pyeval:`constants.ST_LVM_VG`) and ``output_fields``. The result
will be a job id, using which the result can be retrieved.


.. _rapi-res-nodes-node_name-storage-modify:

``/2/nodes/[node_name]/storage/modify``
+++++++++++++++++++++++++++++++++++++++

Modifies storage units on the node.

.. rapi_resource_details:: /2/nodes/[node_name]/storage/modify


.. _rapi-res-nodes-node_name-storage-modify+put:

``PUT``
~~~~~~~

Modifies parameters of storage units on the node. Requires the
parameters ``storage_type`` (one of :pyeval:`constants.ST_FILE`,
:pyeval:`constants.ST_LVM_PV` or :pyeval:`constants.ST_LVM_VG`)
and ``name`` (name of the storage unit).  Parameters can be passed
additionally. Currently only :pyeval:`constants.SF_ALLOCATABLE` (bool)
is supported. The result will be a job id.

Job result:

.. opcode_result:: OP_NODE_MODIFY_STORAGE


.. _rapi-res-nodes-node_name-storage-repair:

``/2/nodes/[node_name]/storage/repair``
+++++++++++++++++++++++++++++++++++++++

Repairs a storage unit on the node.

.. rapi_resource_details:: /2/nodes/[node_name]/storage/repair


.. _rapi-res-nodes-node_name-storage-repair+put:

``PUT``
~~~~~~~

.. pyassert::

   constants.VALID_STORAGE_OPERATIONS == {
    constants.ST_LVM_VG: set([constants.SO_FIX_CONSISTENCY]),
    }

Repairs a storage unit on the node. Requires the parameters
``storage_type`` (currently only :pyeval:`constants.ST_LVM_VG` can be
repaired) and ``name`` (name of the storage unit). The result will be a
job id.

Job result:

.. opcode_result:: OP_REPAIR_NODE_STORAGE


.. _rapi-res-nodes-node_name-tags:

``/2/nodes/[node_name]/tags``
+++++++++++++++++++++++++++++

Manages per-node tags.

.. rapi_resource_details:: /2/nodes/[node_name]/tags


.. _rapi-res-nodes-node_name-tags+get:

``GET``
~~~~~~~

Returns a list of tags.

Example::

    ["tag1", "tag2", "tag3"]


.. _rapi-res-nodes-node_name-tags+put:

``PUT``
~~~~~~~

Add a set of tags.

The request as a list of strings should be PUT to this URI. The result
will be a job id.

It supports the ``dry-run`` argument.


.. _rapi-res-nodes-node_name-tags+delete:

``DELETE``
~~~~~~~~~~

Deletes tags.

In order to delete a set of tags, the DELETE request should be addressed
to URI like::

    /tags?tag=[tag]&tag=[tag]

It supports the ``dry-run`` argument.


.. _rapi-res-query-resource:

``/2/query/[resource]``
+++++++++++++++++++++++

Requests resource information. Available fields can be found in man
pages and using ``/2/query/[resource]/fields``. The resource is one of
:pyeval:`utils.CommaJoin(constants.QR_VIA_RAPI)`. See the :doc:`query2
design document <design-query2>` for more details.

.. rapi_resource_details:: /2/query/[resource]


.. _rapi-res-query-resource+get:

``GET``
~~~~~~~

Returns list of included fields and actual data. Takes a query parameter
named "fields", containing a comma-separated list of field names. Does
not support filtering.


.. _rapi-res-query-resource+put:

``PUT``
~~~~~~~

Returns list of included fields and actual data. The list of requested
fields can either be given as the query parameter "fields" or as a body
parameter with the same name. The optional body parameter "filter" can
be given and must be either ``null`` or a list containing filter
operators.


.. _rapi-res-query-resource-fields:

``/2/query/[resource]/fields``
++++++++++++++++++++++++++++++

Request list of available fields for a resource. The resource is one of
:pyeval:`utils.CommaJoin(constants.QR_VIA_RAPI)`. See the
:doc:`query2 design document <design-query2>` for more details.

.. rapi_resource_details:: /2/query/[resource]/fields


.. _rapi-res-query-resource-fields+get:

``GET``
~~~~~~~

Returns a list of field descriptions for available fields. Takes an
optional query parameter named "fields", containing a comma-separated
list of field names.


.. _rapi-res-os:

``/2/os``
+++++++++

OS resource.

.. rapi_resource_details:: /2/os


.. _rapi-res-os+get:

``GET``
~~~~~~~

Return a list of all OSes.

Can return error 500 in case of a problem. Since this is a costly
operation for Ganeti 2.0, it is not recommended to execute it too often.

Example::

    ["debian-etch"]


.. _rapi-res-tags:

``/2/tags``
+++++++++++

Manages cluster tags.

.. rapi_resource_details:: /2/tags


.. _rapi-res-tags+get:

``GET``
~~~~~~~

Returns the cluster tags.

Example::

    ["tag1", "tag2", "tag3"]


.. _rapi-res-tags+put:

``PUT``
~~~~~~~

Adds a set of tags.

The request as a list of strings should be PUT to this URI. The result
will be a job id.

It supports the ``dry-run`` argument.


.. _rapi-res-tags+delete:

``DELETE``
~~~~~~~~~~

Deletes tags.

In order to delete a set of tags, the DELETE request should be addressed
to URI like::

    /tags?tag=[tag]&tag=[tag]

It supports the ``dry-run`` argument.


.. _rapi-res-version:

``/version``
++++++++++++

The version resource.

This resource should be used to determine the remote API version and to
adapt clients accordingly.

.. rapi_resource_details:: /version


.. _rapi-res-version+get:

``GET``
~~~~~~~

Returns the remote API version. Ganeti 1.2 returned ``1`` and Ganeti 2.0
returns ``2``.


.. _rapi-access-permissions:

Access permissions
------------------

The following list describes the access permissions required for each
resource. See :ref:`rapi-users` for more details.

.. rapi_access_table::


.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
