Ganeti Remote API
=================

.. contents::

Objective
---------
The Ganeti RAPI provides limited remote control over Ganeti-cluster for
third-party applications, exposing internal Ganeti functionality via RESTful
API.


Goals
~~~~~

- Provide functionality for remote cluster management.

- Expose current cluster state

- Must be extensible and revolvable in design

- Restrict access


Requirements
~~~~~~~~~~~~

- Authentication

- Encryption

- Language independent

- Reliable and easy to use


Background
----------

A growing amount of installations can shortly put ganeti based infrastructure
on manageable edge. Therefore the is strong need to centralize clusters
management, provide information for the "best placement" and cluster
rebalancing decisions.

The first Ganeti RAPI was designed and deployed with the Ganeti 1.2.5 release.
That version provide Read-Only access to a cluster state. Fully functional
read-write API demand significant internal changes which are in a pipeline for
Ganeti 2.0 release.

Overview
--------

We decided to go with implementing the Ganeti RAPI in a RESTful way, which is
aligned with key features we looking. It is simple, stateless, scalable and
extensible paradigm of API implementation. As transport it uses HTTP over SSL,
and we are implementing it in JSON encoding, but in a way it possible to extend
and provide any other one.

Design
-------

The Ganeti API implemented as independent daemon, running on the same node
with the same permission level as Ganeti master daemon. Communication done
through unix socket protocol provided by Ganeti luxi library.
In order to keep communication asynchronous RAPI process two types of client
requests:

- queries: sever able to answer immediately
- jobs: some time needed.

In the query case requested data send back to client in http body. Typical
examples of queries would be list of nodes, instances, cluster info, etc.
Dealing with jobs client instead of waiting until job completes receive a job
id, the identifier which allows to query the job progress in the job queue.
(See job queue design doc for details)

Internally, each exported object has an version identifier, which is used as a
state stamp in the http header E-Tag field for request/response to avoid a race
condition.


Resource representation
~~~~~~~~~~~~~~~~~~~~~~~
The key difference of REST approach from others API is instead having one URI
for all our requests, REST demand separate service by resources with unique
URI. Each of them should have limited amount of stateless and standard HTTP
methods: GET, POST, DELETE, PUT.

For example in Ganeti case we can have a set of URI:
 - /{clustername}/instances
 - /{clustername}/instances/{instancename}
 - /{clustername}/instances/{instancename}/tag
 - /{clustername}/tag

A GET request to /{clustername}/instances will return list of instances, a POST
to /{clustername}/instances should create new instance, a DELETE
/{clustername}/instances/{instancename} should delete instance, a GET
/{clustername}/tag get cluster tag

Each resource URI has a version prefix. The complete list of resources id TBD.

Internal encoding might be JSON, XML, or any other. The JSON encoding fits
nicely in Ganeti RAPI needs. Specific representation client can request with
Accept field in the HTTP header.

The REST uses standard HTTP as application protocol (not just as a transport)
for resources access. Set of possible result codes is a subset of standard HTTP
results. The stateless provide additional reliability and transparency to
operations.


Security
~~~~~~~~
With the write functionality security becomes much bigger an issue.  The Ganeti
RAPI uses basic HTTP authentication on top of SSL connection to grant access to
an exported resource. The password stores locally in Apache-style .htpasswd
file. Only one level of privileges is supported.
