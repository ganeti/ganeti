Ganeti remote API
=================

Documents Ganeti version 2.0

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

Usage examples
--------------

You can access the API using your favorite programming language as
long as it supports network connections.

Shell
+++++

Using wget::

  wget -q -O - https://CLUSTERNAME:5080/2/info

or curl::

  curl https://CLUSTERNAME:5080/2/info


Python
++++++

::

  import urllib2
  f = urllib2.urlopen('https://CLUSTERNAME:5080/2/info')
  print f.read()


JavaScript
++++++++++

.. warning:: While it's possible to use JavaScript, it poses several potential
  problems, including browser blocking request due to
  non-standard ports or different domain names. Fetching the data
  on the webserver is easier.

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

/
+

::

  / resource.

It supports the following commands: GET.

GET
~~~

::

  Show the list of mapped resources.

  Returns: a dictionary with 'name' and 'uri' keys for each of them.

/2
++

::

  /2 resource, the root of the version 2 API.

It supports the following commands: GET.

GET
~~~

::

  Show the list of mapped resources.

  Returns: a dictionary with 'name' and 'uri' keys for each of them.

/2/info
+++++++

::

  Cluster info.

It supports the following commands: GET.

GET
~~~

::

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

/2/instances
++++++++++++

::

  /2/instances resource.

It supports the following commands: GET, POST.

GET
~~~

::

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

  If the optional 'bulk' argument is provided and set to 'true'
  value (i.e '?bulk=1'), the output contains detailed
  information about instances as a list.

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

  Returns: a dictionary with 'name' and 'uri' keys for each of them.

POST
~~~~

::

  Create an instance.

  Returns: a job id

/2/instances/[instance_name]
++++++++++++++++++++++++++++

::

  /2/instances/[instance_name] resources.

It supports the following commands: GET, DELETE.

GET
~~~

::

  Send information about an instance.



DELETE
~~~~~~

::

  Delete an instance.



/2/instances/[instance_name]/reboot
+++++++++++++++++++++++++++++++++++

::

  /2/instances/[instance_name]/reboot resource.

  Implements an instance reboot.

It supports the following commands: POST.

POST
~~~~

::

  Reboot an instance.

  The URI takes type=[hard|soft|full] and
  ignore_secondaries=[False|True] parameters.

/2/instances/[instance_name]/shutdown
+++++++++++++++++++++++++++++++++++++

::

  /2/instances/[instance_name]/shutdown resource.

  Implements an instance shutdown.

It supports the following commands: PUT.

PUT
~~~

::

  Shutdown an instance.



/2/instances/[instance_name]/startup
++++++++++++++++++++++++++++++++++++

::

  /2/instances/[instance_name]/startup resource.

  Implements an instance startup.

It supports the following commands: PUT.

PUT
~~~

::

  Startup an instance.

  The URI takes force=[False|True] parameter to start the instance
  if even if secondary disks are failing.

/2/instances/[instance_name]/tags
+++++++++++++++++++++++++++++++++

::

  /2/instances/[instance_name]/tags resource.

  Manages per-instance tags.

It supports the following commands: GET, PUT, DELETE.

GET
~~~

::

  Returns a list of tags.

  Example: ["tag1", "tag2", "tag3"]

PUT
~~~

::

  Add a set of tags.

  The request as a list of strings should be PUT to this URI. And
  you'll have back a job id.

DELETE
~~~~~~

::

  Delete a tag.

  In order to delete a set of tags, the DELETE
  request should be addressed to URI like:
  /tags?tag=[tag]&tag=[tag]

/2/jobs
+++++++

::

  /2/jobs resource.

It supports the following commands: GET.

GET
~~~

::

  Returns a dictionary of jobs.

  Returns: a dictionary with jobs id and uri.

/2/jobs/[job_id]
++++++++++++++++

::

  /2/jobs/[job_id] resource.

It supports the following commands: GET, DELETE.

GET
~~~

::

  Returns a job status.

  Returns: a dictionary with job parameters.
      The result includes:
          - id: job ID as a number
          - status: current job status as a string
          - ops: involved OpCodes as a list of dictionaries for each
            opcodes in the job
          - opstatus: OpCodes status as a list
          - opresult: OpCodes results as a list of lists

DELETE
~~~~~~

::

  Cancel not-yet-started job.



/2/nodes
++++++++

::

  /2/nodes resource.

It supports the following commands: GET.

GET
~~~

::

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

  If the optional 'bulk' argument is provided and set to 'true'
  value (i.e '?bulk=1'), the output contains detailed
  information about nodes as a list.

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

  Returns: a dictionary with 'name' and 'uri' keys for each of them

/2/nodes/[node_name]/tags
+++++++++++++++++++++++++

::

  /2/nodes/[node_name]/tags resource.

  Manages per-node tags.

It supports the following commands: GET, PUT, DELETE.

GET
~~~

::

  Returns a list of tags.

  Example: ["tag1", "tag2", "tag3"]

PUT
~~~

::

  Add a set of tags.

  The request as a list of strings should be PUT to this URI. And
  you'll have back a job id.

DELETE
~~~~~~

::

  Delete a tag.

  In order to delete a set of tags, the DELETE
  request should be addressed to URI like:
  /tags?tag=[tag]&tag=[tag]

/2/os
+++++

::

  /2/os resource.

It supports the following commands: GET.

GET
~~~

::

  Return a list of all OSes.

  Can return error 500 in case of a problem.

  Example: ["debian-etch"]

/2/tags
+++++++

::

  /2/instances/tags resource.

  Manages cluster tags.

It supports the following commands: GET, PUT, DELETE.

GET
~~~

::

  Returns a list of tags.

  Example: ["tag1", "tag2", "tag3"]

PUT
~~~

::

  Add a set of tags.

  The request as a list of strings should be PUT to this URI. And
  you'll have back a job id.

DELETE
~~~~~~

::

  Delete a tag.

  In order to delete a set of tags, the DELETE
  request should be addressed to URI like:
  /tags?tag=[tag]&tag=[tag]

/nodes/[node_name]
++++++++++++++++++

::

  /2/nodes/[node_name] resources.

It supports the following commands: GET.

GET
~~~

::

  Send information about a node.



/version
++++++++

::

  /version resource.

  This resource should be used to determine the remote API version and
  to adapt clients accordingly.

It supports the following commands: GET.

GET
~~~

::

  Returns the remote API version.
