Design for adding a node to a cluster
=====================================

.. contents:: :depth: 3


Note
----

Closely related to this design is the more recent design
:doc:`node security <design-node-security>` which extends and changes
some of the aspects mentioned in this document. Make sure that you
read the more recent design as well to get an up to date picture of
Ganeti's procedure for adding new nodes.


Current state and shortcomings
------------------------------

Before a node can be added to a cluster, its SSH daemon must be
re-configured to use the cluster-wide SSH host key. Ganeti 2.3.0 changed
the way this is done by moving all related code to a separate script,
``tools/setup-ssh``, using Paramiko. Before all such configuration was
done from ``lib/bootstrap.py`` using the system's own SSH client and a
shell script given to said client through parameters.

Both solutions controlled all actions on the connecting machine; the
newly added node was merely executing commands. This implies and
requires a tight coupling and equality between nodes (e.g. paths to
files being the same). Most of the logic and error handling is also done
on the connecting machine.

Once a node's SSH daemon has been configured, more than 25 files need to
be copied using ``scp`` before the node daemon can be started. No
verification is being done before files are copied. Once the node daemon
is started, an opcode is submitted to the master daemon, which will then
copy more files, such as the configuration and job queue for master
candidates, using RPC. This process is somewhat fragile and requires
initiating many SSH connections.

Proposed changes
----------------

SSH
~~~

The main goal is to move more logic to the newly added node. Instead of
having a relatively large script executed on the master node, most of it
is moved over to the added node.

A new script named ``prepare-node-join`` is added. It receives a JSON
data structure (defined :ref:`below <prepare-node-join-json>`) on its
standard input. Once the data has been successfully decoded, it proceeds
to configure the local node's SSH daemon and root's SSH settings, after
which the SSH daemon is restarted.

All the master node has to do to add a new node is to gather all
required data, build the data structure, and invoke the script on the
node to be added. This will enable us to once again use the system's own
SSH client and to drop the dependency on Paramiko for Ganeti itself
(``ganeti-listrunner`` is going to continue using Paramiko).

Eventually ``setup-ssh`` can be removed.


Node daemon
~~~~~~~~~~~

Similar to SSH setup changes, the process of copying files and starting
the node daemon will be moved into a dedicated program. On its standard
input it will receive a standardized JSON structure (defined :ref:`below
<node-daemon-setup-json>`). Once the input data has been successfully
decoded and the received values were verified for sanity, the program
proceeds to write the values to files and then starts the node daemon
(``ganeti-noded``).

To add a new node to the cluster, the master node will have to gather
all values, build the data structure, and then invoke the newly added
``node-daemon-setup`` program via SSH. In this way only a single SSH
connection is needed and the values can be verified before being written
to files.

If the program exits successfully, the node is ready to be added to the
master daemon's configuration. The node daemon will be running, but
``OpNodeAdd`` needs to be run before it becomes a full node. The opcode
will copy more files, such as the :doc:`RAPI certificate <rapi>`.


Data structures
---------------

.. _prepare-node-join-json:

JSON structure for SSH setup
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The data is given in an object containing the keys described below.
Unless specified otherwise, all entries are optional.

``cluster_name``
  Required string with the cluster name. If a local cluster name is
  found, the join process is aborted unless the passed cluster name
  matches the local name.
``node_daemon_certificate``
  Public part of cluster's node daemon certificate in PEM format. If a
  local node certificate and key is found, the join process is aborted
  unless this passed public part can be verified with the local key.
``ssh_host_key``
  List containing public and private parts of SSH host key. See below
  for definition.
``ssh_root_key``
  List containing public and private parts of root's key for SSH
  authorization. See below for definition.

Lists of SSH keys use a tuple with three values. The first describes the
key variant (``rsa`` or ``dsa``). The second and third are the private
and public part of the key. Example:

.. highlight:: javascript

::

  [
    ("rsa", "-----BEGIN RSA PRIVATE KEY-----...", "ssh-rss AAAA..."),
    ("dsa", "-----BEGIN DSA PRIVATE KEY-----...", "ssh-dss AAAA..."),
  ]


.. _node-daemon-setup-json:

JSON structure for node daemon setup
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The data is given in an object containing the keys described below.
Unless specified otherwise, all entries are optional.

``cluster_name``
  Required string with the cluster name. If a local cluster name is
  found, the join process is aborted unless the passed cluster name
  matches the local name. The cluster name is also included in the
  dictionary given via the ``ssconf`` entry.
``node_daemon_certificate``
  Public and private part of cluster's node daemon certificate in PEM
  format. If a local node certificate is found, the process is aborted
  unless it matches.
``ssconf``
  Dictionary with ssconf names and their values. Both are strings.
  Example:

  .. highlight:: javascript

  ::

    {
      "cluster_name": "cluster.example.com",
      "master_ip": "192.168.2.1",
      "master_netdev": "br0",
      # …
    }

``start_node_daemon``
  Boolean denoting whether the node daemon should be started (or
  restarted if it was running for some reason).

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
