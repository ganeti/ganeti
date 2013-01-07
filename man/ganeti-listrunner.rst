ganeti-listrunner(8) Ganeti | Version @GANETI_VERSION@
======================================================

NAME
----

ganeti-listrunner - Run commands in parallel over multiple machines


SYNOPSIS
--------

**ganeti-listrunner** ``-l`` *logdir*
{``-x`` *executable* | ``-c`` *shell-cmd*}
{``-f`` *hostfile* | ``-h`` *hostlist*}
[``-a`` *aux-file*]
[``-b`` *batch-size*]
[``-u`` *username*]
[``-A``]


DESCRIPTION
-----------

**ganeti-listrunner** is a tool to run commands in parallel over multiple
machines. It differs from ``dsh`` or other tools in that it asks for the
password once (if not using ``ssh-agent``) and then reuses the password to
connect to all machines, thus being easily usable even when public key
authentication or Kerberos authentication is not available.

It can run either a command or a script (which gets uploaded first and deleted
after execution) on a  list  of hosts provided either via a file (one host per
line) or as a comma-separated list on the commandline. The output (stdout and
stderr are merged) of the remote execution is written to a logfile. One logfile
per  host  is written.


OPTIONS
-------

The options that can be passed to the program are as follows:

``-l`` *logdir*
  The directory under which the logfiles files should be written.

``-x`` *executable*
  The executable to copy and run on the target hosts.

``-c`` *shell-cmd*
  The shell command to run on the remote hosts.

``-f`` *hostfile*
  The file with the target hosts, one hostname per line.

``-h`` *hostlist*
  Comma-separated list of target hosts.

``-a`` *aux-file*
  A file to copy to the target hosts. Can be given multiple times, in which case
  all files will be copied to the temporary directory. The executable or the
  shell command will be run from the (temporary) directory where these files
  have been copied.

``-b`` *batch-size*
  The host list will be split into batches of batch-size which will be processed
  in parallel. The default if 15, and should be increased if faster processing
  is needed.

``-u`` *username*
  Username to connect as instead of the default root username.

``-A``
  Use an existing ssh-agent instead of password authentication.

``--args``
  Arguments to pass to executable (``-x``).


EXIT STATUS
-----------

The exist status of the command will be zero, unless it was aborted in some way
(e.g. ^C).


EXAMPLE
-------

Run a command on a list of hosts:

.. code-block:: bash

  listrunner -l logdir -c "uname -a" -h host1,host2,host3

Upload a script, some auxiliary files and run the script:

.. code-block:: bash

  listrunner -l logdir -x runme.sh \
    -a seed.dat -a golden.dat \
    -h host1,host2,host3


SEE ALSO
--------

**dsh**\(1), **cssh**\(1)

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
