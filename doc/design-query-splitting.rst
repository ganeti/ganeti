===========================================
Splitting the query and job execution paths
===========================================


Introduction
============

Currently, the master daemon does two main roles:

- execute jobs that change the cluster state
- respond to queries

Due to the technical details of the implementation, the job execution
and query paths interact with each other, and for example the "masterd
hang" issue that we had late in the 2.5 release cycle was due to the
interaction between job queries and job execution.

Furthermore, also because technical implementations (Python lacking
read-only variables being one example), we can't share internal data
structures for jobs; instead, in the query path, we read them from
disk in order to not block job execution due to locks.

All these point to the fact that the integration of both queries and
job execution in the same process (multi-threaded) creates more
problems than advantages, and hence we should look into separating
them.


Proposed design
===============

In Ganeti 2.7, we will introduce a separate, optional daemon to handle
queries (note: whether this is an actual "new" daemon, or its
functionality is folded into confd, remains to be seen).

This daemon will expose exactly the same Luxi interface as masterd,
except that job submission will be disabled. If so configured (at
build time), clients will be changed to:

- keep sending REQ_SUBMIT_JOB, REQ_SUBMIT_MANY_JOBS, and all requests
  except REQ_QUERY_* to the masterd socket (but also QR_LOCK)
- redirect all REQ_QUERY_* requests to the new Luxi socket of the new
  daemon (except generic query with QR_LOCK)

This new daemon will serve both pure configuration queries (which
confd can already serve), and run-time queries (which currently only
masterd can serve). Since the RPC can be done from any node to any
node, the new daemon can run on all master candidates, not only on the
master node. This means that all gnt-* list options can be now run on
other nodes than the master node. If we implement this as a separate
daemon that talks to confd, then we could actually run this on all
nodes of the cluster (to be decided).

During the 2.7 release, masterd will still respond to queries itself,
but it will log all such queries for identification of "misbehaving"
clients.

Advantages
----------

As far as I can see, this will bring some significant advantages.

First, we remove any interaction between the job execution and cluster
query state. This means that bugs in the locking code (job execution)
will not impact the query of the cluster state, nor the query of the
job execution itself. Furthermore, we will be able to have different
tuning parameters between job execution (e.g. 25 threads for job
execution) versus query (since these are transient, we could
practically have unlimited numbers of query threads).

As a result of the above split, we move from the current model, where
shutdown of the master daemon practically "breaks" the entire Ganeti
functionality (no job execution nor queries, not even connecting to
the instance console), to a split model:

- if just masterd is stopped, then other cluster functionality remains
  available: listing instances, connecting to the console of an
  instance, etc.
- if just "luxid" is stopped, masterd can still process jobs, and one
  can furthermore run queries from other nodes (MCs)
- only if both are stopped, we end up with the previous state

This will help, for example, in the case where the master node has
crashed and we haven't failed it over yet: querying and investigating
the cluster state will still be possible from other master candidates
(on small clusters, this will mean from all nodes).

A last advantage is that we finally will be able to reduce the
footprint of masterd; instead of previous discussion of splitting
individual jobs, which requires duplication of all the base
functionality, this will just split the queries, a more trivial piece
of code than job execution. This should be a reasonable work effort,
with a much smaller impact in case of failure (we can still run
masterd as before).

Disadvantages
-------------

We might get increased inconsistency during queries, as there will be
a delay between masterd saving an updated configuration and
confd/query loading and parsing it. However, this could be compensated
by the fact that queries will only look at "snapshots" of the
configuration, whereas before it could also look at "in-progress"
modifications (due to the non-atomic updates). I think these will
cancel each other out, we will have to see in practice how it works.

Another disadvantage *might* be that we have a more complex setup, due
to the introduction of a new daemon. However, the query path will be
much simpler, and when we remove the query functionality from masterd
we should have a more robust system.

Finally, we have QR_LOCK, which is an internal query related to the
master daemon, using the same infrastructure as the other queries
(related to cluster state). This is unfortunate, and will require
untangling in order to keep code duplication low.

Long-term plans
===============

If this works well, the plan would be (tentatively) to disable the
query functionality in masterd completely in Ganeti 2.8, in order to
remove the duplication. This might change based on how/if we split the
configuration/locking daemon out, or not.

Once we split this out, there is not technical reason why we can't
execute any query from any node; except maybe practical reasons
(network topology, remote nodes, etc.) or security reasons (if/whether
we want to change the cluster security model). In any case, it should
be possible to do this in a reliable way from all master candidates.

Update: We decided to keep the restriction to run queries on the master
node. The reason is that it is confusing from a usability point of view
that querying will work on any node and suddenly, when the user tries
to submit a job, it won't work.

Some implementation details
---------------------------

We will fold this in confd, at least initially, to reduce the
proliferation of daemons. Haskell will limit (if used properly) any too
deep integration between the old "confd" functionality and the new query
one. As advantages, we'll have a single daemons that handles
configuration queries.

The redirection of Luxi requests can be easily done based on the
request type, if we have both sockets open, or if we open on demand.

We don't want the masterd to talk to the luxid itself (hidden
redirection), since we want to be able to run queries while masterd is
down.

During the 2.7 release cycle, we can test all queries against both
masterd and luxid in QA, so we know we have exactly the same
interface and it is consistent.

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
