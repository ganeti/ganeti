===============================================
RAPI authentication and authorization using PAM
===============================================

.. contents:: :depth: 4

This design document describes a way of :doc:`rapi` authentication
and authorization refactoring by using the pluggable authentication
modules (PAM).

Current State
=============

Currently :doc:`rapi` supports authentication using *basic auth* over
https protocol. The users are stored in a file (usually
``/var/lib/ganeti/rapi/users``) and have either read or write rights.
Please read :ref:`rapi-users` for more details.

.. _motivation:

Motivation
==========

During GanetiCon 2015 the following features were requested by the
community:

- Support for different authentication methods;
- Granular access to different RAPI command subsets;
- Granular access to different target instances.

The last two statements may be desired when an administrator wants to
provide some restricted cluster or instance management rights for users.

Proposed Implementation
=======================

Ganeti RAPI will use PAM for *authentication* and *account*
(authorization) purposes. ``ganeti-basic`` PAM module performing
*authentication* and *account* based on the contents of
``ganeti/rapi/users`` file will be distributed with Ganeti. Ganeti rapi
will interact with PAM using ``ganeti-rapi`` service name. The default
configuration for ``ganeti-rapi`` PAM service will just use
``ganeti-basic`` module.

A good documentation on client-server PAM model is available
at http://www.linux-pam.org/pre/doc/current-draft.txt.

Authentication Specific Details
-------------------------------

In case of *basic auth* over http, the username and password will
be extracted as they are presented in the
:ref:`standard form <basic-protocol>`. Note, that independent from
authentication method, all interactions will be performed via https
protocol.

In case of another authentication method, additional user's credintials
(e.g. request signature) should be provided in
``Ganeti-RAPI-Credential`` field. The field should be encoded using
base64 algorithm as for the *basic auth* over http.

Ganeti will copy the username to ``PAM_USER`` field of a ``pam_handler``
and the contents of ``Ganeti-RAPI-Credential`` http header fielf to
``PAM_AUTHTOK`` field of a ``pam_handler``.

User's password will be send as a reply to each request made by
*conversation function* with ``PAM_PROMPT_ECHO_OFF`` message constant.
Other requests will be just ignored.

Authorization Specific Details
------------------------------

Ganeti will pass several parameters that might be useful for the
*authorization* phase to the modules via the private PAM environmental
variables (using ``pam_setenv``)

GANETI_RAPI_URI
  The requested URI.
GANETI_REQUEST_BODY
  The body of a request if any or an empty string otherwise.
GANETI_REQUEST_METHOD
  The method of an http request (GET, PUT, POST or DELETE).
GANETI_RESOURCE_ACCESS
  The comma-separated access handlers of a resource if provided in
  rlib2 or empty string otherwise.

One More Time About the Goals
=============================

Support for Different Authentication Methods
--------------------------------------------

The proposed solution allows to use signatures of any kind instead of
user password or in addition to it. It allows an administrator to
support more complex and secure authentication schemes than just a basic
authentication over http.

Granular Access to Different Command Subsets
--------------------------------------------

This functionality can be implemented just by writing more complex
authorization module that will permit or deny execution of some command
based on the environment variables passed and some additional config
file.

Granular Access to Different Target Instances
---------------------------------------------

For such kind of authorization, a PAM module may be implemented as
well. The main difference is that for complex access rights maintaining
the module will have to store users rights and lists of owned objects
on some kind of dynamic database instead of simple static config file.

Switching Between the Old and the New Implementations
-----------------------------------------------------

As the changes introduced should be backwards compatible, a new
ganeti-rapi daemon run-time option ``--enable_pam_rapi`` will be
introduced.

Other Changes
=============

As writing PAM module is an universal solution for the authorization
problem, sometimes such flexibility is not necessary or not
available because of disabled PAM. In that case it is still possible
to provide granular access to the RAPI.

For that purpose ``RAPI-Auth:username`` will be added to the reason
trail just before sending a job for a further processing. That will
allow to configure a filter that will reject job subsets initiated
by some specific user i.e. add a user to a blacklist. See
:doc:`design-optables` for more information about job filters.

Additionally, we propose to introduce a new
:ref:`filter predicate <filter-predicates>`, ``username`` that will
contain the authenticated user's login and thus will make it possible to
define an allowed user set for each operation.
