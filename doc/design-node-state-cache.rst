================
Node State Cache
================

.. contents:: :depth: 4

This is a design doc about the optimization of machine info retrieval.


Current State
=============

Currently every RPC call is quite expensive as a TCP handshake has to be
made as well as SSL negotiation. This especially is visible when getting
node and instance info over and over again.

This data, however, is quite easy to cache but needs some changes to how
we retrieve data in the RPC as this is spread over several RPC calls
and are hard to unify.


Proposed changes
================

To overcome this situation with multiple information retrieval calls we
introduce one single RPC call to get all the info in a organized manner,
for easy store in the cache.

As of now we have 3 different information RPC calls:

- ``call_node_info``: To retrieve disk and hyper-visor information
- ``call_instance_info``: To retrieve hyper-visor information for one
  instance
- ``call_all_instance_info``: To retrieve hyper-visor information for
  all instances

Not to mention that ``call_all_instance_info`` and
``call_instance_info`` return different information in the dict.

To unify the data and organize them we introduce a new RPC call
``call_node_snapshot`` doing all of the above in one go. Which
data we want to know will be specified about a dict of request
types: CACHE_REQ_HV, CACHE_REQ_DISKINFO, CACHE_REQ_BOOTID

As this cache is representing the state of a given node we use the
name of a node as the key to retrieve the data from the cache. A
name-space separation of node and instance data is not possible at the
current point. This is due to the fact that some of the node hyper-visor
information like free memory is correlating with instances running.

An example of how the data for a node in the cache looks like::

  {
    constants.CACHE_REQ_HV: {
      constants.HT_XEN_PVM: {
        _NODE_DATA: {
          "memory_total": 32763,
          "memory_free": 9159,
          "memory_dom0": 1024,
          "cpu_total": 4,
          "cpu_sockets": 2
        },
        _INSTANCES_DATA: {
          "inst1": {
            "memory": 4096,
            "state": "-b----",
            "time": 102399.3,
            "vcpus": 1
          },
          "inst2": {
            "memory": 4096,
            "state": "-b----",
            "time": 12280.0,
            "vcpus": 3
          }
        }
      }
    },
    constants.CACHE_REQ_DISKINFO: {
      "xenvg": {
        "vg_size": 1048576,
        "vg_free": 491520
      },
    }
    constants.CACHE_REQ_BOOTID: "0dd0983c-913d-4ce6-ad94-0eceb77b69f9"
  }

This way we get easy to organize information which can simply be arranged in
the cache.

The 3 RPC calls mentioned above will remain for compatibility reason but
will be simple wrappers around this RPC call.


Cache invalidation
------------------

The cache is invalidated at every RPC call which is not proven to not
modify the state of a given node. This is to avoid inconsistency between
cache and actual node state.

There are some corner cases which invalidates the whole cache at once as
they usually affect other nodes states too:

 - migrate/failover
 - import/export

A request will be served from the cache if and only if it can be
fulfilled entirely from it (i.e. all the CACHE_REQ_* entries are already
present). Otherwise, we will invalidate the cache and actually do the
remote call.

In addition, every cache entry will have a TTL of about 10 minutes which
should be enough to accommodate most use cases.

We also allow an option to the calls to bypass the cache completely and
do a force remote call. However, this will invalidate the present
entries and populate the cache with the new retrieved values.


Additional cache population
---------------------------

Besides of the commands which calls above RPC calls, a full cache
population can also be done by a separate new op-code run by
``ganeti-watcher`` periodically. This op-code will be used instead of
the old ones.


Possible regressions
====================

As we change from getting "one hyper-visor information" to "get all we
know about this hyper-visor"-style we have a regression in time of
execution. The execution time is about 1.8x more in process execution
time. However, this does not include the latency and negotiation time
needed for each separate RPC call. Also if we hit the cache all 3 costs
will be 0. The only time taken is to look up the info in the cache and
the deserialization of the data. Which takes down the time from today
~300ms to ~100ms.

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
