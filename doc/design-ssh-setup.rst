Design for setting up SSH
=====================================

.. contents:: :depth: 3


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


Proposed changes
----------------

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

.. _prepare-node-join-json:

JSON structure
~~~~~~~~~~~~~~

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

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
