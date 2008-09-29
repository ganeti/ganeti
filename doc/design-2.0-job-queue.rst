Job Queue
=========

.. contents::

Overview
--------

In Ganeti 1.2, operations in a cluster have to be done in a serialized way.
Virtually any operation locks the whole cluster by grabbing the global lock.
Other commands can't return before all work has been done.

By implementing a job queue and granular locking, we can lower the latency of
command execution inside a Ganeti cluster.


Detailed Design
---------------

Job execution—“Life of a Ganeti job”
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

#. Job gets submitted by the client. A new job identifier is generated and
   assigned to the job. The job is then automatically replicated to all nodes
   in the cluster. The identifier is returned to the client.
#. A pool of worker threads waits for new jobs. If all are busy, the job has
   to wait and the first worker finishing its work will grab it. Otherwise any
   of the waiting threads will pick up the new job.
#. Client waits for job status updates by calling a waiting RPC function.
   Log message may be shown to the user. Until the job is started, it can also
   be cancelled.
#. As soon as the job is finished, its final result and status can be retrieved
   from the server.
#. If the client archives the job, it gets moved to a history directory.
   This could also be done regularily using a cron script.


Queue structure
~~~~~~~~~~~~~~~

All file operations have to be done atomically by writing to a temporary file
and subsequent renaming. Except for log messages, every change in a job is
stored and replicated to other nodes.

::

  /var/lib/ganeti/queue/
    job-1 (JSON encoded job description and status)
    […]
    job-37
    job-38
    job-39
    lock (Queue managing process opens this file in exclusive mode)
    serial (Last job ID used)
    version (Queue format version)


Locking
~~~~~~~

Locking in the job queue is a complicated topic. It is called from more than
one thread and must be thread-safe. For simplicity, a single lock is used for
the whole job queue.

A more detailed description can be found in doc/locking.txt.


Internal RPC
~~~~~~~~~~~~

RPC calls available between Ganeti master and node daemons:

jobqueue_update(file_name, content)
  Writes a file in the job queue directory.
jobqueue_purge()
  Cleans the job queue directory completely, including archived job.
jobqueue_rename(old, new)
  Renames a file in the job queue directory.


Client RPC
~~~~~~~~~~

RPC between Ganeti clients and the Ganeti master daemon supports the following
operations:

SubmitJob(ops)
  Submits a list of opcodes and returns the job identifier. The identifier is
  guaranteed to be unique during the lifetime of a cluster.
WaitForJobChange(job_id, fields, […], timeout)
  This function waits until a job changes or a timeout expires. The condition
  for when a job changed is defined by the fields passed and the last log
  message received.
QueryJobs(job_ids, fields)
  Returns field values for the job identifiers passed.
CancelJob(job_id)
  Cancels the job specified by identifier. This operation may fail if the job
  is already running, canceled or finished.
ArchiveJob(job_id)
  Moves a job into the …/archive/ directory. This operation will fail if the
  job has not been canceled or finished.


Job and opcode status
~~~~~~~~~~~~~~~~~~~~~

Each job and each opcode has, at any time, one of the following states:

Queued
  The job/opcode was submitted, but did not yet start.
Running
  The job/opcode is running.
Canceled
  The job/opcode was canceled before it started.
Success
  The job/opcode ran and finished successfully.
Error
  The job/opcode was aborted with an error.

If the master is aborted while a job is running, the job will be set to the
Error status once the master started again.


History
~~~~~~~

Archived jobs are kept in a separate directory, /var/lib/ganeti/queue/archive/.
The idea is to speed up the queue handling.


Ganeti updates
~~~~~~~~~~~~~~

The queue has to be completely empty for Ganeti updates with changes in the job
queue structure.
