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
to configure the local node's SSH daemon, the Ganeti node daemon and
restarts both.

All the master node has to do to add a new node is to gather all
required data, build the data structure, and invoke the script on the
node to be added. This will enable us to once again use the system's own
SSH client and to drop the dependency on Paramiko for Ganeti itself
(``ganeti-listrunner`` is going to continue using Paramiko).

Eventually ``setup-ssh`` can be removed.

.. _prepare-node-join-json:

JSON structure
~~~~~~~~~~~~~~

The data is given in an object containing the keys described below. All
entries are optional with the condition that for cryptography keys,
private and public parts or nothing at all must be given.

``ssh_host_key``
  List containing public and private parts of SSH host key. See below
  for definition.
``ssh_root_key``
  List containing public and private parts of root's key for SSH
  authorization. See below for definition.
``node_daemon_certificate``
  Node daemon certificate in PEM format, to be stored in ``server.pem``.
``start_node_daemon``
  Boolean value describing whether the node daemon should be
  started/restarted. If not given, the daemon is not started.

Lists of SSH keys use a tuple with three values. The first describes the
key variant (``rsa`` or ``dsa``). The second and third are the public
and private part of the key. Example:

.. highlight:: javascript

::

  [
    ("rsa", "AAAA...", "-----BEGIN RSA PRIVATE KEY-----..."),
    ("dsa", "AAAA...", "-----BEGIN DSA PRIVATE KEY-----..."),
  ]

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
